from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from AI_agent import extract_json_object, extract_response_text, load_llm_config, post_llm_json
from AI_group_classification import classification_fields, classification_scheme_signature, format_classification_scheme
from RIS_analysis import (
    LiteratureRecord,
    SENTENCE_SPLIT_RE,
    clean_spaces,
    normalize_doi,
    normalize_title,
    truncate,
)
from read_templete import (
    analysis_json_schema,
    build_ai_instructions,
    build_ai_user_prompt,
    get_research_topic,
    template_signature,
)
from project_paths import CACHE_DIR


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


def prepare_runtime_annotations(
    records: list[LiteratureRecord],
    fields: list[str],
    llm_config: dict[str, Any] | None = None,
    classification_scheme: dict[str, Any] | None = None,
) -> dict[int, dict[str, str]]:
    annotations: dict[int, dict[str, str]] = {}
    cache = load_annotation_cache()
    cache_records = cache.setdefault("records", {})
    refresh_ai = os.getenv("LITERATURE_REFRESH_AI", "").strip() == "1"
    use_ai = os.getenv("LITERATURE_USE_AI", "1").strip() != "0"
    llm_config = llm_config or load_llm_config()
    api_key = str(llm_config.get("api_key", "")).strip()
    base_classification_context = format_classification_scheme(classification_scheme or {}, fields)
    if not base_classification_context and classification_fields(fields):
        topic = get_research_topic()
        base_classification_context = (
            "当前没有可用的文献组 AI 分类体系。"
            "请不要自行创建新的分类名称；分类字段填写 broad_direction=AI未分类，"
            "medium_direction=待AI分析，small_direction=待AI分析。"
            f"注意：分类失败只影响分类字段；research_topic_connection、complexity、review_sentence 等分析字段仍必须围绕“{topic}”判断，不能只复述文献内容。"
        )
    signature = "\n".join([template_signature(fields), classification_scheme_signature(classification_scheme or {})])
    cache_changed = False
    missing: list[tuple[int, LiteratureRecord, str]] = []

    for index, record in enumerate(records, start=1):
        key = record_cache_key(record, signature)
        cached = cache_records.get(key, {}) if not refresh_ai else {}
        cached_analysis = normalize_analysis(cached.get("analysis"), fields) if cached else {}
        if cached_analysis:
            annotations[index] = cached_analysis
            continue

        missing.append((index, record, key))

    if missing and api_key and use_ai:
        print(f"需要 AI 阅读的新文献：{len(missing)} 条")
        for position, (index, record, key) in enumerate(missing, start=1):
            print(f"AI 阅读 {position}/{len(missing)}：{record.title[:80] or '未命名文献'}")
            try:
                classification_context = (
                    format_classification_scheme(classification_scheme or {}, fields, record=record)
                    if classification_scheme
                    else base_classification_context
                )
                analysis = annotate_record_with_llm(
                    index,
                    record,
                    llm_config,
                    fields,
                    classification_context or base_classification_context,
                )
            except Exception as exc:
                print(f"AI 阅读失败，改用中性兜底：第 {index} 条，{exc}")
                analysis = {}

            if analysis:
                annotations[index] = analysis
                cache_records[key] = cache_entry(record, analysis, source=str(llm_config.get("provider", "llm")), config=llm_config)
                cache_changed = True
                save_annotation_cache(cache)
                time.sleep(float(llm_config.get("sleep_seconds", 0.2)))
    elif missing:
        if api_key and not use_ai:
            print("已设置 LITERATURE_USE_AI=0，未调用 AI；缺失条目会用中性兜底。")
        else:
            print("未检测到可用 API key；新文献无法自动 AI 阅读，缺失条目会用中性兜底。")

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
    analysis.setdefault("small_direction", fallback["small_direction"])
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


def normalize_analysis(value: Any, fields: list[str]) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    if any(field not in value for field in fields):
        return {}
    return {field: clean_spaces(str(value.get(field, ""))) for field in fields}


def annotate_record_with_llm(
    index: int,
    record: LiteratureRecord,
    config: dict[str, Any],
    fields: list[str],
    classification_context: str,
) -> dict[str, str]:
    endpoint_type = str(config.get("endpoint", "chat_completions"))
    if endpoint_type == "responses":
        return annotate_record_with_responses_api(index, record, config, fields, classification_context)
    if endpoint_type == "anthropic_messages":
        return annotate_record_with_anthropic_messages(index, record, config, fields, classification_context)
    return annotate_record_with_chat_completions(index, record, config, fields, classification_context)


def annotation_max_tokens(config: dict[str, Any]) -> int:
    return int(config.get("annotation_max_tokens", config.get("max_tokens", 2200)))


def annotation_thinking(config: dict[str, Any]) -> Any:
    return config.get("annotation_thinking", config.get("thinking"))


def annotation_reasoning_effort(config: dict[str, Any]) -> Any:
    return config.get("annotation_reasoning_effort", config.get("reasoning_effort"))


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


def annotate_record_with_chat_completions(
    index: int,
    record: LiteratureRecord,
    config: dict[str, Any],
    fields: list[str],
    classification_context: str,
) -> dict[str, str]:
    endpoint = str(config.get("base_url", "https://api.deepseek.com")).rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": config.get("model", "deepseek-v4-pro"),
        "messages": [
            {"role": "system", "content": build_ai_instructions()},
            {"role": "user", "content": build_ai_user_prompt(record_payload(index, record), fields, classification_context)},
        ],
        "temperature": float(config.get("temperature", 0.2)),
        "max_tokens": annotation_max_tokens(config),
    }
    if config.get("json_mode", True):
        payload["response_format"] = {"type": "json_object"}
    thinking = annotation_thinking(config)
    if thinking:
        payload["thinking"] = thinking
    reasoning_effort = annotation_reasoning_effort(config)
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort

    try:
        data = post_llm_json(endpoint, payload, config)
    except RuntimeError as exc:
        if "response_format" not in str(exc):
            raise
        payload.pop("response_format", None)
        data = post_llm_json(endpoint, payload, config)
    content = data["choices"][0]["message"].get("content", "")
    return parse_analysis_response(content, fields)


def annotate_record_with_responses_api(
    index: int,
    record: LiteratureRecord,
    config: dict[str, Any],
    fields: list[str],
    classification_context: str,
) -> dict[str, str]:
    endpoint = str(config.get("base_url", "https://api.openai.com/v1")).rstrip("/") + "/responses"
    payload = {
        "model": config.get("model", "gpt-4o-mini"),
        "instructions": build_ai_instructions(),
        "input": build_ai_user_prompt(record_payload(index, record), fields, classification_context),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "literature_annotation",
                "strict": True,
                "schema": analysis_json_schema(fields),
            }
        },
        "temperature": float(config.get("temperature", 0.2)),
        "max_output_tokens": annotation_max_tokens(config),
    }
    data = post_llm_json(endpoint, payload, config)
    return parse_analysis_response(extract_response_text(data), fields)


def annotate_record_with_anthropic_messages(
    index: int,
    record: LiteratureRecord,
    config: dict[str, Any],
    fields: list[str],
    classification_context: str,
) -> dict[str, str]:
    endpoint = str(config.get("base_url", "https://api.anthropic.com")).rstrip("/") + "/v1/messages"
    payload: dict[str, Any] = {
        "model": config.get("model", "claude-3-5-sonnet-latest"),
        "system": build_ai_instructions(),
        "messages": [{"role": "user", "content": build_ai_user_prompt(record_payload(index, record), fields, classification_context)}],
        "temperature": float(config.get("temperature", 0.2)),
        "max_tokens": annotation_max_tokens(config),
    }
    thinking = annotation_thinking(config)
    if thinking:
        payload["thinking"] = thinking
    data = post_llm_json(endpoint, payload, config)
    content = "\n".join(item.get("text", "") for item in data.get("content", []) if item.get("type") == "text")
    return parse_analysis_response(content, fields)


def parse_analysis_response(text: str, fields: list[str]) -> dict[str, str]:
    analysis = normalize_analysis(json.loads(extract_json_object(text)), fields)
    if not analysis:
        raise RuntimeError("模型返回的 JSON 字段不完整")
    return analysis


def fallback_analysis(record: LiteratureRecord) -> dict[str, str]:
    return {
        "broad_direction": "AI未分类",
        "medium_direction": "待AI分析",
        "small_direction": "待AI分析",
        "abstract_summary": summarize_abstract(record.abstract),
        "study_object": "AI未分析，需配置 API key 后由模型根据当前研究主题判断。",
        "methods": "AI未分析，需配置 API key 后由模型根据当前研究主题判断。",
        "core_result": infer_core_result(record),
        "fcva_connection": "AI未分析，需配置 API key 后由模型判断。",
        "research_topic_connection": "AI未分析，需配置 API key 后由模型判断。",
        "complexity": "AI未分析，需配置 API key 后由模型判断。",
        "review_sentence": "AI未分析，需配置 API key 后由模型生成可用于综述的句子。",
    }


def summarize_abstract(abstract: str, max_length: int = 360) -> str:
    if not abstract:
        return "题录缺摘要，需阅读全文验证。"
    sentences = [sentence.strip() for sentence in SENTENCE_SPLIT_RE.split(abstract) if sentence.strip()]
    summary = " ".join(sentences[:2]) if sentences else abstract
    return truncate(summary, max_length)


def infer_core_result(record: LiteratureRecord) -> str:
    if not record.abstract:
        return "题录缺摘要，需阅读全文验证。"
    markers = ("show", "demonstrat", "result", "found", "indicat", "improv", "increase", "decrease", "enhanc", "表明", "结果", "发现", "提高", "降低", "增强")
    sentences = [sentence.strip() for sentence in SENTENCE_SPLIT_RE.split(record.abstract) if sentence.strip()]
    for sentence in sentences:
        if any(marker in sentence.casefold() for marker in markers):
            return truncate(sentence, 300)
    return truncate(sentences[-1] if sentences else record.abstract, 300)
