from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from AI_agent import extract_json_object, extract_response_text, post_llm_json
from RIS_analysis import LiteratureRecord, clean_spaces, normalize_doi, normalize_title, truncate
from project_paths import CACHE_DIR
from read_templete import (
    read_review_section,
    read_summary_section,
    template_signature,
)


GROUP_CLASSIFICATION_CACHE_PATH = CACHE_DIR / "literature_group_classification.json"
GROUP_CLASSIFICATION_DEBUG_PATH = CACHE_DIR / "literature_group_classification_last_response.json"
CLASSIFICATION_FIELDS = ("broad_direction", "medium_direction", "small_direction")
DEFAULT_GROUP_MAX_TOKENS = 6000


def prepare_classification_scheme(
    records: list[LiteratureRecord],
    fields: list[str],
    llm_config: dict[str, Any],
) -> dict[str, Any]:
    requested_fields = classification_fields(fields)
    if not records or not requested_fields:
        return {}

    cache = load_classification_cache()
    cache_records = cache.setdefault("schemes", {})
    refresh_ai = os.getenv("LITERATURE_REFRESH_AI", "").strip() == "1"
    use_ai = os.getenv("LITERATURE_USE_AI", "1").strip() != "0"
    api_key = str(llm_config.get("api_key", "")).strip()
    key = classification_cache_key(records, fields)

    if not refresh_ai:
        cached = normalize_classification_scheme(cache_records.get(key), requested_fields)
        if cached:
            print(f"已加载 AI 文献组分类体系：{len(cached.get('taxonomy', []))} 个分类")
            return cached

    if not api_key or not use_ai:
        if api_key and not use_ai:
            print("已设置 LITERATURE_USE_AI=0，未生成文献组 AI 分类体系。")
        else:
            print("未检测到可用 API key；无法生成文献组 AI 分类体系，分类将标记为 AI未分类。")
        return {}

    print("正在让 AI 根据当前研究主题和整组文献生成分类体系...")
    try:
        scheme = annotate_group_classification(records, fields, llm_config)
    except Exception as exc:
        print(f"AI 文献组分类体系生成失败，分类将标记为 AI未分类：{exc}")
        return {}
    cache_records[key] = {
        "source": str(llm_config.get("provider", "llm")),
        "model": llm_config.get("model", ""),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "scheme": scheme,
    }
    save_classification_cache(cache)
    print(f"AI 文献组分类体系已生成：{len(scheme.get('taxonomy', []))} 个分类")
    return scheme


def classification_fields(fields: list[str]) -> list[str]:
    return [field for field in CLASSIFICATION_FIELDS if field in fields]


def load_classification_cache() -> dict[str, Any]:
    if not GROUP_CLASSIFICATION_CACHE_PATH.exists():
        return {"version": 1, "schemes": {}}
    try:
        return json.loads(GROUP_CLASSIFICATION_CACHE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "schemes": {}}


def save_classification_cache(cache: dict[str, Any]) -> None:
    GROUP_CLASSIFICATION_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    GROUP_CLASSIFICATION_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def classification_cache_key(records: list[LiteratureRecord], fields: list[str]) -> str:
    record_material = "\n\n".join(record_digest(record) for record in records)
    material = "\n\n".join([template_signature(fields), record_material])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def record_digest(record: LiteratureRecord) -> str:
    return "\n".join(
        [
            normalize_doi(record.doi),
            normalize_title(record.title),
            record.year,
            record.journal.casefold(),
            clean_spaces(record.abstract),
            ";".join(clean_spaces(keyword).casefold() for keyword in record.keywords),
        ]
    )


def annotate_group_classification(
    records: list[LiteratureRecord],
    fields: list[str],
    config: dict[str, Any],
) -> dict[str, Any]:
    endpoint_type = str(config.get("endpoint", "chat_completions"))
    if endpoint_type == "responses":
        return annotate_group_with_responses_api(records, fields, config)
    if endpoint_type == "anthropic_messages":
        return annotate_group_with_anthropic_messages(records, fields, config)
    return annotate_group_with_chat_completions(records, fields, config)


def annotate_group_with_chat_completions(
    records: list[LiteratureRecord],
    fields: list[str],
    config: dict[str, Any],
) -> dict[str, Any]:
    endpoint = str(config.get("base_url", "https://api.deepseek.com")).rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": config.get("model", "deepseek-v4-pro"),
        "messages": [
            {"role": "system", "content": build_group_classification_instructions()},
            {"role": "user", "content": build_group_classification_prompt(records, fields)},
        ],
        "temperature": float(config.get("temperature", 0.2)),
        "max_tokens": group_max_tokens(config),
    }
    if config.get("json_mode", True):
        payload["response_format"] = {"type": "json_object"}
    if config.get("thinking"):
        payload["thinking"] = config["thinking"]
    if config.get("reasoning_effort"):
        payload["reasoning_effort"] = config["reasoning_effort"]

    data = post_llm_json(endpoint, payload, config)
    content = chat_message_text(data)
    try:
        return parse_classification_response(content, fields)
    except Exception as exc:
        save_group_classification_debug(data, content, exc)
        return retry_group_classification_json(endpoint, payload, records, fields, config, content, exc)


def annotate_group_with_responses_api(
    records: list[LiteratureRecord],
    fields: list[str],
    config: dict[str, Any],
) -> dict[str, Any]:
    endpoint = str(config.get("base_url", "https://api.openai.com/v1")).rstrip("/") + "/responses"
    payload = {
        "model": config.get("model", "gpt-4o-mini"),
        "instructions": build_group_classification_instructions(),
        "input": build_group_classification_prompt(records, fields),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "literature_group_classification",
                "strict": True,
                "schema": classification_json_schema(fields),
            }
        },
        "temperature": float(config.get("temperature", 0.2)),
        "max_output_tokens": group_max_tokens(config),
    }
    data = post_llm_json(endpoint, payload, config)
    content = extract_response_text(data)
    try:
        return parse_classification_response(content, fields)
    except Exception as exc:
        save_group_classification_debug(data, content, exc)
        raise


def annotate_group_with_anthropic_messages(
    records: list[LiteratureRecord],
    fields: list[str],
    config: dict[str, Any],
) -> dict[str, Any]:
    endpoint = str(config.get("base_url", "https://api.anthropic.com")).rstrip("/") + "/v1/messages"
    payload: dict[str, Any] = {
        "model": config.get("model", "claude-3-5-sonnet-latest"),
        "system": build_group_classification_instructions(),
        "messages": [{"role": "user", "content": build_group_classification_prompt(records, fields)}],
        "temperature": float(config.get("temperature", 0.2)),
        "max_tokens": group_max_tokens(config),
    }
    if config.get("thinking"):
        payload["thinking"] = config["thinking"]
    data = post_llm_json(endpoint, payload, config)
    content = "\n".join(item.get("text", "") for item in data.get("content", []) if item.get("type") == "text")
    try:
        return parse_classification_response(content, fields)
    except Exception as exc:
        save_group_classification_debug(data, content, exc)
        raise


def group_max_tokens(config: dict[str, Any]) -> int:
    env_value = os.getenv("LITERATURE_GROUP_MAX_TOKENS", "").strip()
    if env_value.isdigit():
        return int(env_value)
    configured = int(config.get("group_max_tokens", config.get("max_tokens", DEFAULT_GROUP_MAX_TOKENS)))
    return max(configured, DEFAULT_GROUP_MAX_TOKENS)


def chat_message_text(data: dict[str, Any]) -> str:
    choices = data.get("choices", [])
    if not choices:
        return ""
    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        texts = [item.get("text", "") for item in content if isinstance(item, dict)]
        joined = "\n".join(text for text in texts if text)
        if joined.strip():
            return joined
    return ""


def retry_group_classification_json(
    endpoint: str,
    payload: dict[str, Any],
    records: list[LiteratureRecord],
    fields: list[str],
    config: dict[str, Any],
    previous_text: str,
    previous_error: Exception,
) -> dict[str, Any]:
    retry_payload = dict(payload)
    retry_payload.pop("thinking", None)
    retry_payload.pop("reasoning_effort", None)
    retry_payload["max_tokens"] = group_max_tokens(config)
    retry_payload["messages"] = [
        {
            "role": "system",
            "content": "你只输出合法 JSON 对象，不输出解释、Markdown、代码围栏或思考过程。",
        },
        {
            "role": "user",
            "content": build_group_classification_retry_prompt(records, fields, previous_text, previous_error),
        },
    ]
    data = post_llm_json(endpoint, retry_payload, config)
    content = chat_message_text(data)
    try:
        return parse_classification_response(content, fields)
    except Exception as exc:
        save_group_classification_debug(data, content, exc)
        raise


def build_group_classification_instructions() -> str:
    review_prompt = read_review_section("AI_READING_PROMPT")
    summary_prompt = read_summary_section("SUMMARY_PROMPT")
    return "\n\n".join(
        [
            review_prompt,
            summary_prompt,
            "你需要先根据当前研究主题和整组文献自动归纳分类体系。",
            "分类名称必须来自你对这批文献的理解，不要沿用任何预设材料体系或工艺类别。",
            "输出必须是合法 JSON 对象，不要输出 Markdown 或解释文字。",
        ]
    )


def build_group_classification_prompt(records: list[LiteratureRecord], fields: list[str]) -> str:
    requested_fields = classification_fields(fields)
    field_text = "、".join(requested_fields)
    example_fields = {field: "..." for field in requested_fields}
    example_fields.update({"description": "...", "representative_indices": ["1", "2"]})
    return "\n".join(
        [
            "请阅读下面这一组 RIS 文献题录，围绕 AI_READING_PROMPT 中的研究主题，自动生成后续逐篇文献标注要使用的分类体系。",
            f"分类字段：{field_text}",
            "",
            "要求：",
            "1. 只能根据当前研究主题和这组文献本身归纳分类，不要使用 Python 规则或固定关键词分类。",
            "2. 分类体系要能覆盖这组文献中的主要研究脉络。",
            "3. 分类名称要适合后续写入 broad_direction、medium_direction、small_direction 等字段。",
            "4. taxonomy 中每个分类都要给出 description，帮助后续逐篇文献归类。",
            "5. 如果 small_direction 不在输出字段中，也可以省略或留空。",
            "",
            "请输出 JSON：",
            json.dumps({"taxonomy": [example_fields]}, ensure_ascii=False),
            "",
            "文献组：",
            *[format_record_for_group_prompt(index, record) for index, record in enumerate(records, start=1)],
        ]
    )


def build_group_classification_retry_prompt(
    records: list[LiteratureRecord],
    fields: list[str],
    previous_text: str,
    previous_error: Exception,
) -> str:
    requested_fields = classification_fields(fields)
    example_fields = {field: "..." for field in requested_fields}
    example_fields.update({"description": "...", "representative_indices": ["1", "2"]})
    previous_excerpt = truncate(previous_text, 1200) if previous_text else "上一轮没有返回可解析文本。"
    return "\n".join(
        [
            "上一轮文献组分类结果不是合法 JSON，需要重新生成。",
            f"解析错误：{previous_error}",
            f"上一轮返回片段：{previous_excerpt}",
            "",
            "请重新阅读下面的文献组，只输出一个合法 JSON 对象。",
            "不要输出 Markdown，不要输出解释，不要输出代码围栏。",
            "JSON 结构必须完全类似：",
            json.dumps({"taxonomy": [example_fields]}, ensure_ascii=False),
            "",
            "文献组：",
            *[format_record_for_group_prompt(index, record) for index, record in enumerate(records, start=1)],
        ]
    )


def format_record_for_group_prompt(index: int, record: LiteratureRecord) -> str:
    return "\n".join(
        [
            f"[{index}]",
            f"title: {record.title or '未提供'}",
            f"year: {record.year or '未提供'}",
            f"journal: {record.journal or '未提供'}",
            f"keywords: {'; '.join(record.keywords) or '未提供'}",
            f"abstract: {truncate(record.abstract, 600) or '未提供'}",
        ]
    )


def classification_json_schema(fields: list[str]) -> dict[str, Any]:
    requested_fields = classification_fields(fields)
    category_properties: dict[str, Any] = {
        field: {"type": "string"} for field in requested_fields
    }
    category_properties.update(
        {
            "description": {"type": "string"},
            "representative_indices": {"type": "array", "items": {"type": "string"}},
        }
    )
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "taxonomy": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": category_properties,
                    "required": [*requested_fields, "description", "representative_indices"],
                },
            }
        },
        "required": ["taxonomy"],
    }


def parse_classification_response(text: str, fields: list[str]) -> dict[str, Any]:
    data = json.loads(extract_json_object(text))
    scheme = normalize_classification_scheme(data, classification_fields(fields))
    if not scheme:
        raise RuntimeError("模型返回的文献组分类体系不完整")
    return scheme


def save_group_classification_debug(data: dict[str, Any], content: str, error: Exception) -> None:
    GROUP_CLASSIFICATION_DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)
    debug_data = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "error": str(error),
        "content": content,
        "response": data,
    }
    GROUP_CLASSIFICATION_DEBUG_PATH.write_text(json.dumps(debug_data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_classification_scheme(value: Any, requested_fields: list[str]) -> dict[str, Any]:
    if isinstance(value, dict) and isinstance(value.get("scheme"), dict):
        value = value["scheme"]
    if not isinstance(value, dict):
        return {}
    taxonomy = value.get("taxonomy")
    if not isinstance(taxonomy, list):
        return {}

    normalized_items: list[dict[str, Any]] = []
    for item in taxonomy:
        if not isinstance(item, dict):
            continue
        normalized: dict[str, Any] = {}
        missing_required = False
        for field in requested_fields:
            text = clean_spaces(str(item.get(field, "")))
            if not text and field != "small_direction":
                missing_required = True
                break
            normalized[field] = text
        if missing_required:
            continue
        normalized["description"] = clean_spaces(str(item.get("description", "")))
        indices = item.get("representative_indices", [])
        if isinstance(indices, list):
            normalized["representative_indices"] = [clean_spaces(str(index)) for index in indices if clean_spaces(str(index))]
        else:
            normalized["representative_indices"] = []
        normalized_items.append(normalized)

    if not normalized_items:
        return {}
    return {"taxonomy": normalized_items}


def format_classification_scheme(scheme: dict[str, Any], fields: list[str]) -> str:
    taxonomy = scheme.get("taxonomy", []) if isinstance(scheme, dict) else []
    if not taxonomy:
        return ""

    lines = [
        "当前文献组已经由 AI 根据研究主题生成如下分类体系。",
        "逐篇文献输出分类字段时，应优先从该体系中选择最合适的一组分类；只有确实不匹配时才使用“AI未分类/待AI复核”。",
    ]
    requested_fields = classification_fields(fields)
    for index, item in enumerate(taxonomy, start=1):
        parts = [f"{field}={item.get(field, '')}" for field in requested_fields if item.get(field, "")]
        description = item.get("description", "")
        if description:
            parts.append(f"description={description}")
        lines.append(f"{index}. " + "；".join(parts))
    return "\n".join(lines)


def classification_scheme_signature(scheme: dict[str, Any]) -> str:
    material = json.dumps(scheme or {}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
