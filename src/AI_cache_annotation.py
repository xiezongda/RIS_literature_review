from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from RIS_analysis import (
    LiteratureRecord,
    SENTENCE_SPLIT_RE,
    clean_spaces,
    has_any,
    normalize_doi,
    normalize_title,
    searchable_text,
    truncate,
)
from read_templete import (
    analysis_json_schema,
    build_ai_instructions,
    build_ai_user_prompt,
    template_signature,
)

try:
    from literature_annotations import LITERATURE_ANNOTATIONS
except ImportError:
    LITERATURE_ANNOTATIONS = {}


ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "output" / "cache"
CONFIG_DIR = ROOT / "config"
AI_CACHE_PATH = CACHE_DIR / "literature_ai_annotations.json"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def prepare_runtime_annotations(records: list[LiteratureRecord], fields: list[str]) -> dict[int, dict[str, str]]:
    annotations: dict[int, dict[str, str]] = {}
    cache = load_annotation_cache()
    cache_records = cache.setdefault("records", {})
    refresh_ai = os.getenv("LITERATURE_REFRESH_AI", "").strip() == "1"
    use_ai = os.getenv("LITERATURE_USE_AI", "1").strip() != "0"
    llm_config = load_llm_config()
    api_key = str(llm_config.get("api_key", "")).strip()
    signature = template_signature(fields)
    cache_changed = False
    missing: list[tuple[int, LiteratureRecord, str]] = []

    for index, record in enumerate(records, start=1):
        key = record_cache_key(record, signature)
        cached = cache_records.get(key, {}) if not refresh_ai else {}
        cached_analysis = normalize_analysis(cached.get("analysis"), fields) if cached else {}
        if cached_analysis:
            annotations[index] = cached_analysis
            continue

        preset = preset_annotation_for_current_records(index, records, fields)
        if preset and not refresh_ai:
            annotations[index] = preset
            cache_records[key] = cache_entry(record, preset, source="preset", config=llm_config)
            cache_changed = True
            continue

        missing.append((index, record, key))

    if missing and api_key and use_ai:
        print(f"需要 AI 阅读的新文献：{len(missing)} 条")
        for position, (index, record, key) in enumerate(missing, start=1):
            print(f"AI 阅读 {position}/{len(missing)}：{record.title[:80] or '未命名文献'}")
            try:
                analysis = annotate_record_with_llm(index, record, llm_config, fields)
            except Exception as exc:
                print(f"AI 阅读失败，改用规则兜底：第 {index} 条，{exc}")
                analysis = {}

            if analysis:
                annotations[index] = analysis
                cache_records[key] = cache_entry(record, analysis, source=str(llm_config.get("provider", "llm")), config=llm_config)
                cache_changed = True
                save_annotation_cache(cache)
                time.sleep(float(llm_config.get("sleep_seconds", 0.2)))
    elif missing:
        if api_key and not use_ai:
            print("已设置 LITERATURE_USE_AI=0，未调用 AI；缺失条目会用规则兜底。")
        else:
            print("未检测到可用 API key；新文献无法自动 AI 阅读，缺失条目会用规则兜底。")

    if cache_changed:
        save_annotation_cache(cache)

    return annotations


def build_analysis(record: LiteratureRecord, fields: list[str], override: dict[str, str] | None = None) -> dict[str, str]:
    fallback = fallback_analysis(record)
    analysis: dict[str, str] = {}
    override = override or {}
    for field in fields:
        value = override.get(field)
        if value is None:
            value = fallback.get(field, "")
        analysis[field] = clean_spaces(str(value))

    # Keep grouping stable even when the user forgets to list these fields in AI_USER_PROMPT.
    analysis.setdefault("broad_direction", fallback["broad_direction"])
    analysis.setdefault("medium_direction", fallback["medium_direction"])
    return analysis


def load_annotation_cache() -> dict[str, Any]:
    if not AI_CACHE_PATH.exists():
        return {"version": 2, "records": {}}
    try:
        return json.loads(AI_CACHE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 2, "records": {}}


def save_annotation_cache(cache: dict[str, Any]) -> None:
    AI_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    AI_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def load_llm_config() -> dict[str, Any]:
    agent = os.getenv("LITERATURE_AGENT", "deepseek").strip().lower()
    explicit_path = os.getenv("LITERATURE_AGENT_CONFIG", "").strip()
    config_path = Path(explicit_path) if explicit_path else default_config_path(agent)
    config = default_agent_config(agent)

    if config_path.exists():
        try:
            file_config = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(file_config, dict):
                config.update(file_config)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"AI agent 配置文件不是合法 JSON：{config_path}，{exc}") from exc

    apply_environment_overrides(config)
    placeholder_keys = {"", "填入你的 DeepSeek API Key", "sk-your-deepseek-api-key", "sk-your-openai-api-key", "sk-ant-your-claude-api-key"}
    if str(config.get("api_key", "")).strip() in placeholder_keys:
        config["api_key"] = ""
    return config


def default_config_path(agent: str) -> Path:
    mapping = {
        "deepseek": CONFIG_DIR / "deepseek_v4pro.json",
        "chatgpt": CONFIG_DIR / "chatgpt.json",
        "openai": CONFIG_DIR / "chatgpt.json",
        "claude": CONFIG_DIR / "claude.json",
        "anthropic": CONFIG_DIR / "claude.json",
    }
    return mapping.get(agent, CONFIG_DIR / f"{agent}.json")


def default_agent_config(agent: str) -> dict[str, Any]:
    if agent in {"chatgpt", "openai"}:
        return {
            "provider": "openai",
            "api_key": "",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "endpoint": "responses",
            "temperature": 0.2,
            "max_tokens": 2200,
            "timeout_seconds": 180,
            "sleep_seconds": 0.2,
        }
    if agent in {"claude", "anthropic"}:
        return {
            "provider": "anthropic",
            "api_key": "",
            "base_url": "https://api.anthropic.com",
            "model": "claude-3-5-sonnet-latest",
            "endpoint": "anthropic_messages",
            "temperature": 0.2,
            "max_tokens": 2200,
            "timeout_seconds": 180,
            "sleep_seconds": 0.2,
            "anthropic_version": "2023-06-01",
        }
    return {
        "provider": "deepseek",
        "api_key": "",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-pro",
        "endpoint": "chat_completions",
        "temperature": 0.2,
        "max_tokens": 2200,
        "timeout_seconds": 180,
        "sleep_seconds": 0.2,
        "json_mode": True,
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
    }


def apply_environment_overrides(config: dict[str, Any]) -> None:
    env_api_key = (
        os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("CLAUDE_API_KEY")
        or os.getenv("LITERATURE_API_KEY")
    )
    if env_api_key:
        config["api_key"] = env_api_key
    for env_name, key in (
        ("LITERATURE_BASE_URL", "base_url"),
        ("LITERATURE_MODEL", "model"),
        ("DEEPSEEK_BASE_URL", "base_url"),
        ("DEEPSEEK_MODEL", "model"),
        ("OPENAI_BASE_URL", "base_url"),
        ("OPENAI_MODEL", "model"),
        ("ANTHROPIC_MODEL", "model"),
    ):
        value = os.getenv(env_name)
        if value:
            config[key] = value


def record_cache_key(record: LiteratureRecord, signature: str) -> str:
    material = "\n".join(
        [
            signature,
            normalize_doi(record.doi),
            normalize_title(record.title),
            record.year,
            record.journal.casefold(),
            clean_spaces(record.abstract),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def cache_entry(record: LiteratureRecord, analysis: dict[str, str], source: str, config: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": source,
        "model": config.get("model", ""),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "title": record.title,
        "doi": record.doi,
        "analysis": analysis,
    }


def preset_annotation_for_current_records(index: int, records: list[LiteratureRecord], fields: list[str]) -> dict[str, str]:
    if not LITERATURE_ANNOTATIONS:
        return {}
    if len(records) != len(LITERATURE_ANNOTATIONS):
        return {}
    source_names = {name for record in records for name in record.source_files}
    if source_names != {"YSZ_calculation_computation.ris"}:
        return {}
    return normalize_analysis(LITERATURE_ANNOTATIONS.get(index), fields)


def normalize_analysis(value: Any, fields: list[str]) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    if any(field not in value for field in fields):
        return {}
    return {field: clean_spaces(str(value.get(field, ""))) for field in fields}


def annotate_record_with_llm(index: int, record: LiteratureRecord, config: dict[str, Any], fields: list[str]) -> dict[str, str]:
    endpoint_type = str(config.get("endpoint", "chat_completions"))
    if endpoint_type == "responses":
        return annotate_record_with_responses_api(index, record, config, fields)
    if endpoint_type == "anthropic_messages":
        return annotate_record_with_anthropic_messages(index, record, config, fields)
    return annotate_record_with_chat_completions(index, record, config, fields)


def record_payload(index: int, record: LiteratureRecord) -> dict[str, str]:
    return {
        "index": str(index),
        "title": record.title or "未提供",
        "authors": "; ".join(record.authors) or "未提供",
        "year": record.year or "未提供",
        "journal": record.journal or "未提供",
        "doi": record.doi or "未提供",
        "keywords": "; ".join(record.keywords) or "未提供",
        "abstract": truncate(record.abstract, 7000) or "未提供",
    }


def annotate_record_with_chat_completions(index: int, record: LiteratureRecord, config: dict[str, Any], fields: list[str]) -> dict[str, str]:
    endpoint = str(config.get("base_url", "https://api.deepseek.com")).rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": config.get("model", "deepseek-v4-pro"),
        "messages": [
            {"role": "system", "content": build_ai_instructions()},
            {"role": "user", "content": build_ai_user_prompt(record_payload(index, record), fields)},
        ],
        "temperature": float(config.get("temperature", 0.2)),
        "max_tokens": int(config.get("max_tokens", 2200)),
    }
    if config.get("json_mode", True):
        payload["response_format"] = {"type": "json_object"}
    if config.get("thinking"):
        payload["thinking"] = config["thinking"]
    if config.get("reasoning_effort"):
        payload["reasoning_effort"] = config["reasoning_effort"]

    try:
        data = post_llm_json(endpoint, payload, config)
    except RuntimeError as exc:
        if "response_format" not in str(exc):
            raise
        payload.pop("response_format", None)
        data = post_llm_json(endpoint, payload, config)
    content = data["choices"][0]["message"].get("content", "")
    return parse_analysis_response(content, fields)


def annotate_record_with_responses_api(index: int, record: LiteratureRecord, config: dict[str, Any], fields: list[str]) -> dict[str, str]:
    endpoint = str(config.get("base_url", "https://api.openai.com/v1")).rstrip("/") + "/responses"
    payload = {
        "model": config.get("model", "gpt-4o-mini"),
        "instructions": build_ai_instructions(),
        "input": build_ai_user_prompt(record_payload(index, record), fields),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "literature_annotation",
                "strict": True,
                "schema": analysis_json_schema(fields),
            }
        },
        "temperature": float(config.get("temperature", 0.2)),
        "max_output_tokens": int(config.get("max_tokens", 2200)),
    }
    data = post_llm_json(endpoint, payload, config)
    return parse_analysis_response(extract_response_text(data), fields)


def annotate_record_with_anthropic_messages(index: int, record: LiteratureRecord, config: dict[str, Any], fields: list[str]) -> dict[str, str]:
    endpoint = str(config.get("base_url", "https://api.anthropic.com")).rstrip("/") + "/v1/messages"
    payload: dict[str, Any] = {
        "model": config.get("model", "claude-3-5-sonnet-latest"),
        "system": build_ai_instructions(),
        "messages": [{"role": "user", "content": build_ai_user_prompt(record_payload(index, record), fields)}],
        "temperature": float(config.get("temperature", 0.2)),
        "max_tokens": int(config.get("max_tokens", 2200)),
    }
    if config.get("thinking"):
        payload["thinking"] = config["thinking"]
    data = post_llm_json(endpoint, payload, config)
    content = "\n".join(item.get("text", "") for item in data.get("content", []) if item.get("type") == "text")
    return parse_analysis_response(content, fields)


def post_llm_json(endpoint: str, payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    provider = str(config.get("provider", "")).lower()
    if provider in {"anthropic", "claude"}:
        headers = {
            "x-api-key": str(config["api_key"]),
            "anthropic-version": str(config.get("anthropic_version", "2023-06-01")),
            "Content-Type": "application/json",
        }
    else:
        headers = {
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json",
        }

    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=int(config.get("timeout_seconds", 180)),
            )
            if response.status_code >= 400:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
            return response.json()
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(2 * attempt)
    raise RuntimeError(str(last_error))


def parse_analysis_response(text: str, fields: list[str]) -> dict[str, str]:
    analysis = normalize_analysis(json.loads(extract_json_object(text)), fields)
    if not analysis:
        raise RuntimeError("模型返回的 JSON 字段不完整")
    return analysis


def extract_response_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    texts: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str):
                texts.append(text)
    if texts:
        return "\n".join(texts)
    raise RuntimeError("无法从 API 响应中提取文本")


def extract_json_object(text: str) -> str:
    import re

    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    if text.startswith("{") and text.endswith("}"):
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    raise RuntimeError("模型响应中没有找到 JSON 对象")


def fallback_analysis(record: LiteratureRecord) -> dict[str, str]:
    broad, medium = classify_record(record)
    study_object = infer_study_object(record)
    methods = infer_methods(record)
    connection = infer_research_topic_connection(record)
    return {
        "broad_direction": broad,
        "medium_direction": medium,
        "small_direction": "",
        "abstract_summary": summarize_abstract(record.abstract),
        "study_object": study_object,
        "methods": methods,
        "core_result": infer_core_result(record),
        "fcva_connection": connection,
        "research_topic_connection": connection,
        "complexity": infer_complexity(record),
        "review_sentence": build_review_sentence(record, study_object, methods),
    }


def classify_record(record: LiteratureRecord) -> tuple[str, str]:
    text = searchable_text(record)
    if has_any(text, "simulation", "model", "finite element", "density functional", "dft", "phase-field", "模拟", "建模"):
        return "综述、理论与方法框架", "建模与模拟"
    if has_any(text, "fcva", "filtered cathodic vacuum arc", "cathodic vacuum arc", "vacuum arc", "阴极真空弧", "真空弧"):
        return "薄膜与涂层制备", "FCVA/阴极真空弧沉积"
    if has_any(text, "sputter", "pvd", "pld", "physical vapor", "magnetron", "evaporation", "溅射", "物理气相", "脉冲激光"):
        return "薄膜与涂层制备", "PVD/溅射/PLD 制备"
    if has_any(text, "ysz", "yttria-stabilized zirconia", "yttria stabilized zirconia", "zirconia", "zro2", "氧化锆", "钇稳定"):
        if has_any(text, "thermal barrier", "tbc", "热障"):
            return "YSZ/氧化锆材料性能", "热障涂层与热稳定性"
        if has_any(text, "ionic conductivity", "electrolyte", "sofc", "fuel cell", "离子电导", "电解质", "燃料电池"):
            return "YSZ/氧化锆材料性能", "离子导电与电化学性能"
        return "YSZ/氧化锆材料性能", "相结构、稳定化与基础性能"
    return "其他与待人工复核", "待人工分类"


def summarize_abstract(abstract: str, max_length: int = 360) -> str:
    if not abstract:
        return "题录缺摘要，需阅读全文验证。"
    sentences = [sentence.strip() for sentence in SENTENCE_SPLIT_RE.split(abstract) if sentence.strip()]
    summary = " ".join(sentences[:2]) if sentences else abstract
    return truncate(summary, max_length)


def infer_study_object(record: LiteratureRecord) -> str:
    text = searchable_text(record)
    objects: list[str] = []
    object_terms = [
        ("YSZ/钇稳定氧化锆", ("ysz", "yttria-stabilized zirconia", "yttria stabilized zirconia", "钇稳定")),
        ("氧化锆/ZrO2", ("zirconia", "zro2", "氧化锆")),
        ("薄膜/涂层", ("thin film", "film", "coating", "薄膜", "涂层")),
        ("热障涂层", ("thermal barrier", "tbc", "热障")),
        ("固体氧化物燃料电池相关电解质", ("sofc", "fuel cell", "electrolyte", "燃料电池", "电解质")),
    ]
    for label, needles in object_terms:
        if any(needle in text for needle in needles):
            objects.append(label)
    return "、".join(dict.fromkeys(objects)) if objects else "根据题录信息暂无法明确，建议阅读全文后补充。"


def infer_methods(record: LiteratureRecord) -> str:
    text = searchable_text(record)
    methods: list[str] = []
    method_terms = [
        ("FCVA/阴极真空弧沉积", ("fcva", "filtered cathodic vacuum arc", "cathodic vacuum arc", "vacuum arc", "阴极真空弧", "真空弧")),
        ("磁控溅射/PVD", ("sputter", "magnetron", "pvd", "physical vapor", "溅射", "物理气相")),
        ("PLD", ("pld", "pulsed laser", "脉冲激光")),
        ("CVD/ALD", ("cvd", "chemical vapor", "ald", "atomic layer", "化学气相", "原子层沉积")),
        ("XRD", ("xrd", "x-ray diffraction", "x ray diffraction")),
        ("SEM/TEM", ("sem", "tem", "electron microscopy", "电子显微")),
        ("XPS/Raman/AFM", ("xps", "raman", "afm")),
        ("电化学测试", ("impedance", "eis", "electrochemical", "电化学", "阻抗")),
        ("模拟/建模", ("simulation", "model", "finite element", "dft", "模拟", "建模")),
    ]
    for label, needles in method_terms:
        if any(needle in text for needle in needles):
            methods.append(label)
    return "；".join(dict.fromkeys(methods)) if methods else "题录中未显式给出方法，建议结合全文补充。"


def infer_core_result(record: LiteratureRecord) -> str:
    if not record.abstract:
        return "题录缺摘要，需阅读全文验证。"
    markers = ("show", "demonstrat", "result", "found", "indicat", "improv", "increase", "decrease", "enhanc", "表明", "结果", "发现", "提高", "降低", "增强")
    sentences = [sentence.strip() for sentence in SENTENCE_SPLIT_RE.split(record.abstract) if sentence.strip()]
    for sentence in sentences:
        if has_any(sentence.casefold(), *markers):
            return truncate(sentence, 300)
    return truncate(sentences[-1] if sentences else record.abstract, 300)


def infer_research_topic_connection(record: LiteratureRecord) -> str:
    text = searchable_text(record)
    if has_any(text, "fcva", "filtered cathodic vacuum arc", "cathodic vacuum arc", "vacuum arc", "阴极真空弧"):
        return "可直接对照 FCVA 工艺参数、离子能量、沉积温度、膜层致密性和缺陷控制。"
    if has_any(text, "ysz", "yttria", "zirconia", "zro2", "氧化锆", "钇稳定"):
        return "可为 YSZ 薄膜的相结构稳定、氧空位调控、热/电性能评价提供材料依据。"
    if has_any(text, "thin film", "film", "coating", "sputter", "pvd", "pld", "薄膜", "涂层", "溅射"):
        return "可作为室温薄膜沉积路线、表征指标和工艺-结构-性能关系的横向对比。"
    return "与主题的直接关联度需要人工复核，可优先检查材料体系、制备温度和表征指标是否可迁移。"


def infer_complexity(record: LiteratureRecord) -> str:
    text = searchable_text(record)
    if has_any(text, "fcva", "pld", "ald", "cvd", "magnetron", "sputter", "vacuum", "真空", "溅射", "原子层"):
        return "设备依赖较强，实验复杂性偏高；若已有真空沉积平台，可通过小样片和参数矩阵逐步验证。"
    if has_any(text, "simulation", "model", "review", "模拟", "建模", "综述"):
        return "实验负担较低，但需要转换为可验证的参数假设或评价指标。"
    return "复杂性暂无法从题录判断，建议优先核对设备条件、样品制备周期和关键表征需求。"


def build_review_sentence(record: LiteratureRecord, study_object: str, methods: str) -> str:
    authors = record.authors[0] if record.authors else "相关研究"
    year = f"（{record.year}）" if record.year else ""
    title_topic = record.title or study_object
    if methods.startswith("题录中未显式"):
        return f"{authors}{year}围绕“{truncate(title_topic, 80)}”开展研究，为理解 {study_object} 的结构与性能关系提供了参考。"
    return f"{authors}{year}以 {study_object} 为对象，采用 {methods} 等方法，讨论了“{truncate(title_topic, 80)}”相关问题，可为材料制备与性能评价提供参考。"
