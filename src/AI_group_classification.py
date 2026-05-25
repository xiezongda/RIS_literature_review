from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime
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
DEFAULT_GROUP_BATCH_SIZE = 25
DEFAULT_GROUP_MAX_INPUT_CHARS = 60000
DEFAULT_GROUP_RECORD_ABSTRACT_CHARS = 300
DEFAULT_GROUP_MAX_TAXONOMY_ITEMS = 60
DEFAULT_GROUP_MERGE_SIZE = 8
DEFAULT_CLASSIFICATION_CONTEXT_DESCRIPTION_CHARS = 28
DEFAULT_CLASSIFICATION_CONTEXT_CANDIDATE_LIMIT = 20
DEFAULT_CLASSIFICATION_CONTEXT_CANDIDATE_THRESHOLD = 120


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
        compatible_cached = load_compatible_classification_scheme(cache_records, records, fields, requested_fields)
        if compatible_cached:
            print(
                "已加载兼容的 AI 文献组分类体系："
                f"{len(compatible_cached.get('taxonomy', []))} 个分类。"
                "如需按当前分类设置重建，请设置 LITERATURE_REFRESH_AI=1。"
            )
            return compatible_cached

    if not api_key or not use_ai:
        if api_key and not use_ai:
            print("已设置 LITERATURE_USE_AI=0，未生成文献组 AI 分类体系。")
        else:
            print("未检测到可用 API key；无法生成文献组 AI 分类体系，分类将标记为 AI未分类。")
        return {}

    mode = group_classification_mode(records, fields)
    if mode == "batch":
        print("正在使用大文献组模式：分批归纳文献分类体系，再合并为全局分类体系...")
    else:
        print("正在让 AI 根据当前研究主题和整组文献生成分类体系...")
    try:
        if mode == "batch":
            scheme = annotate_large_group_classification(records, fields, llm_config, cache)
        else:
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
        return {"version": 2, "schemes": {}, "batch_schemes": {}}
    try:
        return json.loads(GROUP_CLASSIFICATION_CACHE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 2, "schemes": {}, "batch_schemes": {}}


def save_classification_cache(cache: dict[str, Any]) -> None:
    GROUP_CLASSIFICATION_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    GROUP_CLASSIFICATION_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def classification_cache_key(
    records: list[LiteratureRecord],
    fields: list[str],
    settings: dict[str, Any] | None = None,
) -> str:
    record_material = "\n\n".join(record_digest(record) for record in records)
    material = "\n\n".join([classification_settings_signature(settings), template_signature(fields), record_material])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def classification_settings(max_taxonomy_items: int | None = None) -> dict[str, Any]:
    return {
        "version": "group-classification-v3-chinese-taxonomy",
        "mode": os.getenv("LITERATURE_GROUP_MODE", "auto").strip().lower() or "auto",
        "batch_size": group_batch_size(),
        "max_input_chars": group_max_input_chars(),
        "record_abstract_chars": group_record_abstract_chars(),
        "max_taxonomy_items": max_taxonomy_items if max_taxonomy_items is not None else group_max_taxonomy_items(),
        "merge_size": group_merge_size(),
    }


def classification_settings_signature(settings: dict[str, Any] | None = None) -> str:
    settings = settings or classification_settings()
    return json.dumps(settings, ensure_ascii=False, sort_keys=True)


def load_compatible_classification_scheme(
    cache_records: dict[str, Any],
    records: list[LiteratureRecord],
    fields: list[str],
    requested_fields: list[str],
) -> dict[str, Any]:
    for key in compatible_classification_cache_keys(records, fields):
        cached = normalize_classification_scheme(cache_records.get(key), requested_fields)
        if cached:
            return cached
    return {}


def compatible_classification_cache_keys(records: list[LiteratureRecord], fields: list[str]) -> list[str]:
    current_items = group_max_taxonomy_items()
    candidate_item_limits = [30, 40, 50, 60, 80, 100]
    keys: list[str] = []
    for item_limit in candidate_item_limits:
        if item_limit == current_items:
            continue
        settings = classification_settings(max_taxonomy_items=item_limit)
        keys.append(classification_cache_key(records, fields, settings=settings))
    return keys


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


def group_classification_mode(records: list[LiteratureRecord], fields: list[str]) -> str:
    mode = os.getenv("LITERATURE_GROUP_MODE", "auto").strip().lower()
    if mode in {"single", "legacy", "once", "one"}:
        return "single"
    if mode in {"batch", "large", "chunk", "chunked"}:
        return "batch"
    if mode and mode != "auto":
        print(f"未知 LITERATURE_GROUP_MODE={mode}，已按 auto 处理。")

    if len(records) > group_batch_size():
        return "batch"
    if estimate_group_prompt_chars(records, fields) > group_max_input_chars():
        return "batch"
    return "single"


def estimate_group_prompt_chars(records: list[LiteratureRecord], fields: list[str]) -> int:
    base = len(build_group_classification_instructions()) + 1200 + 20 * len(fields)
    record_chars = sum(len(format_record_for_group_prompt(index, record)) for index, record in enumerate(records, start=1))
    return base + record_chars


def env_int(name: str, default: int, minimum: int = 1) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        print(f"环境变量 {name}={value} 不是整数，已使用默认值 {default}。")
        return default
    return max(parsed, minimum)


def group_batch_size() -> int:
    return env_int("LITERATURE_GROUP_BATCH_SIZE", DEFAULT_GROUP_BATCH_SIZE, minimum=1)


def group_max_input_chars() -> int:
    return env_int("LITERATURE_GROUP_MAX_INPUT_CHARS", DEFAULT_GROUP_MAX_INPUT_CHARS, minimum=8000)


def group_record_abstract_chars() -> int:
    return env_int("LITERATURE_GROUP_RECORD_ABSTRACT_CHARS", DEFAULT_GROUP_RECORD_ABSTRACT_CHARS, minimum=80)


def group_max_taxonomy_items() -> int:
    return env_int("LITERATURE_GROUP_MAX_TAXONOMY_ITEMS", DEFAULT_GROUP_MAX_TAXONOMY_ITEMS, minimum=5)


def group_merge_size() -> int:
    return env_int("LITERATURE_GROUP_MERGE_SIZE", DEFAULT_GROUP_MERGE_SIZE, minimum=2)


def group_json_thinking_enabled() -> bool:
    return os.getenv("LITERATURE_GROUP_USE_THINKING", "").strip() == "1"


def classification_context_description_chars() -> int:
    return env_int(
        "LITERATURE_CLASSIFICATION_CONTEXT_DESCRIPTION_CHARS",
        DEFAULT_CLASSIFICATION_CONTEXT_DESCRIPTION_CHARS,
        minimum=0,
    )


def classification_context_candidate_limit() -> int:
    return env_int(
        "LITERATURE_CLASSIFICATION_CONTEXT_CANDIDATE_LIMIT",
        DEFAULT_CLASSIFICATION_CONTEXT_CANDIDATE_LIMIT,
        minimum=1,
    )


def classification_context_candidate_threshold() -> int:
    return env_int(
        "LITERATURE_CLASSIFICATION_CONTEXT_CANDIDATE_THRESHOLD",
        DEFAULT_CLASSIFICATION_CONTEXT_CANDIDATE_THRESHOLD,
        minimum=1,
    )


def classification_context_mode() -> str:
    mode = os.getenv("LITERATURE_CLASSIFICATION_CONTEXT_MODE", "compact").strip().lower()
    if mode in {"compact", "full", "candidates", "candidate", "auto"}:
        return mode
    print(f"未知 LITERATURE_CLASSIFICATION_CONTEXT_MODE={mode}，已按 compact 处理。")
    return "compact"


def apply_group_json_reasoning_controls(payload: dict[str, Any], config: dict[str, Any]) -> None:
    if group_json_thinking_enabled():
        if config.get("thinking"):
            payload["thinking"] = config["thinking"]
        if config.get("reasoning_effort"):
            payload["reasoning_effort"] = config["reasoning_effort"]
        return

    provider = str(config.get("provider", "")).lower()
    if provider == "deepseek" and config.get("thinking"):
        payload["thinking"] = {"type": "disabled"}


def post_group_classification_json(endpoint: str, payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    try:
        return post_llm_json(endpoint, payload, config)
    except RuntimeError as exc:
        if "thinking" not in str(exc).lower():
            raise
        retry_payload = dict(payload)
        retry_payload.pop("thinking", None)
        return post_llm_json(endpoint, retry_payload, config)


def annotate_large_group_classification(
    records: list[LiteratureRecord],
    fields: list[str],
    config: dict[str, Any],
    cache: dict[str, Any],
) -> dict[str, Any]:
    indexed_records = list(enumerate(records, start=1))
    batches = split_group_batches(indexed_records, fields)
    print(
        f"大文献组模式：{len(records)} 篇文献拆为 {len(batches)} 批，"
        f"每批最多 {group_batch_size()} 篇。"
    )

    batch_cache = cache.setdefault("batch_schemes", {})
    refresh_ai = os.getenv("LITERATURE_REFRESH_AI", "").strip() == "1"
    batch_schemes: list[dict[str, Any]] = []
    for batch_number, batch in enumerate(batches, start=1):
        batch_key = classification_batch_cache_key(batch, fields)
        cached = normalize_classification_scheme(batch_cache.get(batch_key), classification_fields(fields)) if not refresh_ai else {}
        if cached:
            print(f"已加载第 {batch_number}/{len(batches)} 批局部分类：{len(cached.get('taxonomy', []))} 个分类")
            batch_schemes.append(cached)
            continue

        first_index, last_index = batch[0][0], batch[-1][0]
        print(f"正在生成第 {batch_number}/{len(batches)} 批局部分类：文献 {first_index}-{last_index}")
        prompt = build_group_classification_prompt_from_indexed_records(
            batch,
            fields,
            abstract_chars=group_record_abstract_chars(),
            task_name="请阅读下面这一批 RIS 文献题录，先生成这批文献的局部分类体系。",
        )
        scheme = annotate_classification_prompt(prompt, fields, config)
        batch_cache[batch_key] = {
            "source": str(config.get("provider", "llm")),
            "model": config.get("model", ""),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "record_indices": [index for index, _record in batch],
            "scheme": scheme,
        }
        batch_schemes.append(scheme)
        save_classification_cache(cache)
        time.sleep(float(config.get("sleep_seconds", 0.2)))

    return merge_classification_schemes(batch_schemes, fields, config)


def split_group_batches(
    indexed_records: list[tuple[int, LiteratureRecord]],
    fields: list[str],
) -> list[list[tuple[int, LiteratureRecord]]]:
    max_records = group_batch_size()
    max_chars = group_max_input_chars()
    abstract_chars = group_record_abstract_chars()
    overhead = len(build_group_classification_prompt_from_indexed_records([], fields, abstract_chars=abstract_chars))
    batches: list[list[tuple[int, LiteratureRecord]]] = []
    current: list[tuple[int, LiteratureRecord]] = []
    current_chars = overhead

    for index, record in indexed_records:
        record_chars = len(format_record_for_group_prompt(index, record, abstract_chars=abstract_chars)) + 2
        would_exceed_count = len(current) >= max_records
        would_exceed_chars = current and current_chars + record_chars > max_chars
        if would_exceed_count or would_exceed_chars:
            batches.append(current)
            current = []
            current_chars = overhead
        current.append((index, record))
        current_chars += record_chars

    if current:
        batches.append(current)
    return batches


def classification_batch_cache_key(indexed_records: list[tuple[int, LiteratureRecord]], fields: list[str]) -> str:
    record_material = "\n\n".join(f"{index}\n{record_digest(record)}" for index, record in indexed_records)
    material = "\n\n".join(
        [
            "batch-classification-v1",
            classification_settings_signature(),
            template_signature(fields),
            record_material,
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def merge_classification_schemes(
    schemes: list[dict[str, Any]],
    fields: list[str],
    config: dict[str, Any],
) -> dict[str, Any]:
    requested_fields = classification_fields(fields)
    active = [normalize_classification_scheme(scheme, requested_fields) for scheme in schemes]
    active = [scheme for scheme in active if scheme]
    if not active:
        return {}
    if len(active) == 1:
        return active[0]

    round_number = 1
    merge_size = group_merge_size()
    while len(active) > 1:
        merged_round: list[dict[str, Any]] = []
        groups = list(chunk_list(active, merge_size))
        for group_number, group in enumerate(groups, start=1):
            if len(group) == 1:
                merged_round.append(group[0])
                continue
            print(f"正在合并第 {round_number} 轮分类体系：{group_number}/{len(groups)}")
            prompt = build_merge_classification_prompt(group, fields)
            merged = annotate_classification_prompt(prompt, fields, config, schema_name="literature_group_classification_merge")
            merged_round.append(merged)
            time.sleep(float(config.get("sleep_seconds", 0.2)))
        active = merged_round
        round_number += 1
    return active[0]


def chunk_list(values: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def annotate_group_classification(
    records: list[LiteratureRecord],
    fields: list[str],
    config: dict[str, Any],
) -> dict[str, Any]:
    prompt = build_group_classification_prompt(records, fields)
    return annotate_classification_prompt(prompt, fields, config)


def annotate_classification_prompt(
    prompt: str,
    fields: list[str],
    config: dict[str, Any],
    schema_name: str = "literature_group_classification",
) -> dict[str, Any]:
    endpoint_type = str(config.get("endpoint", "chat_completions"))
    if endpoint_type == "responses":
        return annotate_group_with_responses_api(prompt, fields, config, schema_name)
    if endpoint_type == "anthropic_messages":
        return annotate_group_with_anthropic_messages(prompt, fields, config)
    return annotate_group_with_chat_completions(prompt, fields, config)


def annotate_group_with_chat_completions(
    prompt: str,
    fields: list[str],
    config: dict[str, Any],
) -> dict[str, Any]:
    endpoint = str(config.get("base_url", "https://api.deepseek.com")).rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": config.get("model", "deepseek-v4-pro"),
        "messages": [
            {"role": "system", "content": build_group_classification_instructions()},
            {"role": "user", "content": prompt},
        ],
        "temperature": float(config.get("temperature", 0.2)),
        "max_tokens": group_max_tokens(config),
    }
    if config.get("json_mode", True):
        payload["response_format"] = {"type": "json_object"}
    apply_group_json_reasoning_controls(payload, config)

    data = post_group_classification_json(endpoint, payload, config)
    content = chat_message_text(data)
    try:
        return parse_classification_response(content, fields)
    except Exception as exc:
        save_group_classification_debug(data, content, exc)
        return retry_group_classification_json(endpoint, payload, prompt, fields, config, content, exc)


def annotate_group_with_responses_api(
    prompt: str,
    fields: list[str],
    config: dict[str, Any],
    schema_name: str = "literature_group_classification",
) -> dict[str, Any]:
    endpoint = str(config.get("base_url", "https://api.openai.com/v1")).rstrip("/") + "/responses"
    payload = {
        "model": config.get("model", "gpt-4o-mini"),
        "instructions": build_group_classification_instructions(),
        "input": prompt,
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
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
    prompt: str,
    fields: list[str],
    config: dict[str, Any],
) -> dict[str, Any]:
    endpoint = str(config.get("base_url", "https://api.anthropic.com")).rstrip("/") + "/v1/messages"
    payload: dict[str, Any] = {
        "model": config.get("model", "claude-3-5-sonnet-latest"),
        "system": build_group_classification_instructions(),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": float(config.get("temperature", 0.2)),
        "max_tokens": group_max_tokens(config),
    }
    if group_json_thinking_enabled() and config.get("thinking"):
        payload["thinking"] = config["thinking"]
    data = post_group_classification_json(endpoint, payload, config)
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
    source_prompt: str,
    fields: list[str],
    config: dict[str, Any],
    previous_text: str,
    previous_error: Exception,
) -> dict[str, Any]:
    retry_payload = dict(payload)
    apply_group_json_reasoning_controls(retry_payload, config)
    retry_payload.pop("reasoning_effort", None)
    retry_payload["max_tokens"] = group_max_tokens(config)
    retry_payload["messages"] = [
        {
            "role": "system",
            "content": "你只输出合法 JSON 对象，不输出解释、Markdown、代码围栏或思考过程。",
        },
        {
            "role": "user",
            "content": build_group_classification_retry_prompt(source_prompt, fields, previous_text, previous_error),
        },
    ]
    data = post_group_classification_json(endpoint, retry_payload, config)
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
            "分类名称必须来自你对这批文献和当前研究主题的理解，不要沿用任何预设领域体系或固定类别。",
            "输出必须是合法 JSON 对象，不要输出 Markdown 或解释文字。",
        ]
    )


def build_group_classification_prompt(records: list[LiteratureRecord], fields: list[str]) -> str:
    return build_group_classification_prompt_from_indexed_records(list(enumerate(records, start=1)), fields)


def build_group_classification_prompt_from_indexed_records(
    indexed_records: list[tuple[int, LiteratureRecord]],
    fields: list[str],
    abstract_chars: int = 600,
    task_name: str = "请阅读下面这一组 RIS 文献题录，围绕 AI_READING_PROMPT 中的研究主题，自动生成后续逐篇文献标注要使用的分类体系。",
) -> str:
    requested_fields = classification_fields(fields)
    field_text = "、".join(requested_fields)
    example_fields = {field: "..." for field in requested_fields}
    example_fields.update({"description": "...", "representative_indices": ["1", "2"]})
    return "\n".join(
        [
            task_name,
            "分类必须围绕 AI_READING_PROMPT 中的研究主题，并服务于后续逐篇文献标注。",
            f"分类字段：{field_text}",
            "",
            "要求：",
            "1. 只能根据当前研究主题和这组文献本身归纳分类，不要使用 Python 规则或固定关键词分类。",
            "2. 分类体系要能覆盖这组文献中的主要研究脉络。",
            "3. broad_direction、medium_direction、small_direction 的分类名称必须使用中文短语，不要使用英文分类名。",
            "4. 分类名称要适合后续写入 broad_direction、medium_direction、small_direction 等字段。",
            f"5. 全局 taxonomy 目标控制在 {group_max_taxonomy_items()} 个叶子分类以内；相近分类必须合并，不要为少量文献单独造类。",
            "6. taxonomy 中每个分类都要给出简短中文 description，帮助后续逐篇文献归类。",
            "7. 如果 small_direction 不在输出字段中，也可以省略或留空。",
            "",
            "请输出 JSON：",
            json.dumps({"taxonomy": [example_fields]}, ensure_ascii=False),
            "",
            "文献组：",
            *[
                format_record_for_group_prompt(index, record, abstract_chars=abstract_chars)
                for index, record in indexed_records
            ],
        ]
    )


def build_merge_classification_prompt(schemes: list[dict[str, Any]], fields: list[str]) -> str:
    requested_fields = classification_fields(fields)
    field_text = "、".join(requested_fields)
    example_fields = {field: "..." for field in requested_fields}
    example_fields.update({"description": "...", "representative_indices": ["1", "2"]})
    merge_payload = [
        {
            "source": f"batch_or_round_{index}",
            "taxonomy": scheme.get("taxonomy", []),
        }
        for index, scheme in enumerate(schemes, start=1)
    ]
    return "\n".join(
        [
            "下面是若干批文献已经生成的局部分类体系。请将它们合并成一个全局分类体系，供后续所有文献逐篇标注使用。",
            f"分类字段：{field_text}",
            f"全局 taxonomy 目标不超过 {group_max_taxonomy_items()} 个叶子分类；如果局部分类语义相近，请合并并统一命名。",
            "合并后的 broad_direction、medium_direction、small_direction 必须全部改写为中文分类名；不要保留英文分类名称。",
            "",
            "合并要求：",
            "1. 只合并分类体系，不要重新发明与当前研究主题和文献证据无关的新分类。",
            "2. 保留能覆盖主要研究脉络的 broad_direction、medium_direction、small_direction 层级。",
            "3. 分类名称必须是来自当前研究主题和当前文献的中文短语，不要输出英文标题，也不要沿用其他主题的示例词。",
            "4. description 要用简短中文说明该分类适合归入哪些文献，便于后续逐篇选择。",
            "5. representative_indices 合并各局部分类中的代表文献序号，保留少量最有代表性的序号即可；不要因为单个序号而新建过细分类。",
            "6. 输出必须是一个合法 JSON 对象，不要输出 Markdown 或解释文字。",
            "",
            "请输出 JSON：",
            json.dumps({"taxonomy": [example_fields]}, ensure_ascii=False),
            "",
            "局部分类体系：",
            json.dumps(merge_payload, ensure_ascii=False, indent=2),
        ]
    )


def build_group_classification_retry_prompt(
    source_prompt: str,
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
            "原始任务和文献材料如下：",
            source_prompt,
        ]
    )


def format_record_for_group_prompt(index: int, record: LiteratureRecord, abstract_chars: int = 600) -> str:
    return "\n".join(
        [
            f"[{index}]",
            f"title: {record.title or '未提供'}",
            f"year: {record.year or '未提供'}",
            f"journal: {record.journal or '未提供'}",
            f"keywords: {'; '.join(record.keywords) or '未提供'}",
            f"abstract: {truncate(record.abstract, abstract_chars) or '未提供'}",
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


def compact_classification_items(scheme: dict[str, Any], fields: list[str]) -> list[dict[str, str]]:
    taxonomy = scheme.get("taxonomy", []) if isinstance(scheme, dict) else []
    requested_fields = classification_fields(fields)
    description_limit = classification_context_description_chars()
    compact_items: list[dict[str, str]] = []
    seen_paths: set[tuple[str, ...]] = set()

    for item in taxonomy:
        if not isinstance(item, dict):
            continue
        compact_item: dict[str, str] = {}
        for field in requested_fields:
            value = clean_spaces(str(item.get(field, "")))
            compact_item[field] = value

        path_key = tuple(compact_item.get(field, "") for field in requested_fields)
        if not any(path_key) or path_key in seen_paths:
            continue
        seen_paths.add(path_key)

        description = clean_spaces(str(item.get("description", "")))
        if description_limit <= 0:
            description = ""
        elif description:
            description = truncate(description, description_limit)
        compact_item["description"] = description
        compact_items.append(compact_item)

    return compact_items


def format_classification_scheme(
    scheme: dict[str, Any],
    fields: list[str],
    record: LiteratureRecord | None = None,
) -> str:
    compact_items = compact_classification_items(scheme, fields)
    if not compact_items:
        return ""

    mode = classification_context_mode()
    use_candidates = record is not None and mode in {"candidates", "candidate"}
    use_candidates = use_candidates or (
        record is not None
        and mode == "auto"
        and len(compact_items) > classification_context_candidate_threshold()
    )
    selected_items = (
        select_candidate_classifications(record, compact_items, fields, classification_context_candidate_limit())
        if use_candidates and record is not None
        else compact_items
    )

    requested_fields = classification_fields(fields)
    lines = [
        "当前文献组分类体系如下，已压缩为分类路径和简短说明。",
        "逐篇文献输出分类字段时，优先从这些中文分类中选择；确实不匹配时才使用“AI未分类/待AI复核”。",
        "分类路径格式为 broad_direction > medium_direction > small_direction。",
    ]

    if use_candidates:
        lines.extend(
            [
                "当前仅列出与这篇文献最相关的候选叶子分类，并保留上级分类概览；不要新增英文分类名。",
                "可用上级分类概览：",
                *format_classification_overview(compact_items, requested_fields),
                "候选叶子分类：",
            ]
        )
    else:
        lines.append("分类字段 broad_direction、medium_direction、small_direction 必须输出中文分类名；不要新增英文分类名。")

    for index, item in enumerate(selected_items, start=1):
        lines.append(format_compact_classification_item(index, item, requested_fields))
    return "\n".join(lines)


def format_compact_classification_item(index: int, item: dict[str, str], requested_fields: list[str]) -> str:
    path = " > ".join(item.get(field, "") for field in requested_fields if item.get(field, ""))
    description = item.get("description", "")
    if description:
        return f"{index}. {path}；说明：{description}"
    return f"{index}. {path}"


def format_classification_overview(items: list[dict[str, str]], requested_fields: list[str]) -> list[str]:
    overview_fields = requested_fields[:2] if len(requested_fields) > 1 else requested_fields[:1]
    if not overview_fields:
        return []

    seen: set[tuple[str, ...]] = set()
    lines: list[str] = []
    for item in items:
        path = tuple(item.get(field, "") for field in overview_fields)
        if not any(path) or path in seen:
            continue
        seen.add(path)
        lines.append("- " + " > ".join(part for part in path if part))
    return lines


def select_candidate_classifications(
    record: LiteratureRecord,
    items: list[dict[str, str]],
    fields: list[str],
    limit: int,
) -> list[dict[str, str]]:
    record_text = "\n".join(
        [
            record.title,
            record.journal,
            "; ".join(record.keywords),
            truncate(record.abstract, 1200),
        ]
    )
    record_units = text_match_units(record_text)
    requested_fields = classification_fields(fields)
    scored: list[tuple[int, int, dict[str, str]]] = []
    for index, item in enumerate(items):
        item_text = " ".join([*(item.get(field, "") for field in requested_fields), item.get("description", "")])
        item_units = text_match_units(item_text)
        score = len(record_units & item_units)
        scored.append((score, -index, item))

    scored.sort(reverse=True)
    selected = [item for _score, _negative_index, item in scored[:limit]]
    return selected or items[:limit]


def text_match_units(text: str) -> set[str]:
    text = clean_spaces(text).casefold()
    if not text:
        return set()

    units = set(re.findall(r"[a-z0-9][a-z0-9_+-]{1,}", text))
    cjk_chars = [char for char in text if "\u4e00" <= char <= "\u9fff"]
    units.update("".join(cjk_chars[index : index + 2]) for index in range(max(0, len(cjk_chars) - 1)))
    units.update("".join(cjk_chars[index : index + 3]) for index in range(max(0, len(cjk_chars) - 2)))
    return {unit for unit in units if unit.strip()}


def classification_scheme_signature(scheme: dict[str, Any]) -> str:
    material = json.dumps(scheme or {}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
