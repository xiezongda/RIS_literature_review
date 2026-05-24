from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = ROOT / "propmts"

REVIEW_TEMPLATE_PATHS = [
    PROMPTS_DIR / "review_template.md",
    PROMPTS_DIR / "review_templete.md",
    ROOT / "review_templete.md",
    ROOT / "prompts" / "review_template.md",
]
SUMMARY_TEMPLATE_PATHS = [
    PROMPTS_DIR / "summary_template.md",
    PROMPTS_DIR / "sunmary_templete.md",
    PROMPTS_DIR / "summary_templete.md",
    ROOT / "sunmary_templete.md",
    ROOT / "summary_templete.md",
    ROOT / "prompts" / "summary_template.md",
]

DEFAULT_AI_FIELDS = [
    "broad_direction",
    "medium_direction",
    "small_direction",
    "abstract_summary",
    "study_object",
    "methods",
    "core_result",
    "research_topic_connection",
    "complexity",
    "review_sentence",
]


def read_review_section(section: str, default: str = "") -> str:
    return read_template_section(REVIEW_TEMPLATE_PATHS, section, default)


def read_summary_section(section: str, default: str = "") -> str:
    return read_template_section(SUMMARY_TEMPLATE_PATHS, section, default)


def read_template_section(paths: list[Path], section: str, default: str = "") -> str:
    for path in paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        start_marker = f"<!-- {section}_START -->"
        end_marker = f"<!-- {section}_END -->"
        start = text.find(start_marker)
        end = text.find(end_marker)
        if start == -1 or end == -1 or end <= start:
            continue
        content = text[start + len(start_marker) : end].strip()
        return content or default
    return default


def get_ai_field_descriptions() -> dict[str, str]:
    user_prompt = read_review_section("AI_USER_PROMPT", default_ai_user_prompt())
    fields: dict[str, str] = {}
    for raw_line in user_prompt.splitlines():
        line = raw_line.strip()
        match = re.match(r"^(?:[-*]\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*[:：]\s*(.*)$", line)
        if not match:
            continue
        key, description = match.group(1), match.group(2).strip()
        if key not in fields:
            fields[key] = description

    if fields:
        return fields
    return {key: "" for key in DEFAULT_AI_FIELDS}


def get_ai_fields() -> list[str]:
    return list(get_ai_field_descriptions().keys())


def get_card_template() -> str:
    return read_review_section("CARD_TEMPLATE", default_card_template())


def get_summary_header_template() -> str:
    return read_summary_section("SUMMARY_HEADER_TEMPLATE", default_summary_header_template())


def get_dataview_table_template() -> str:
    return read_summary_section("DATAVIEW_TABLE_TEMPLATE", default_dataview_table_template())


def build_ai_instructions() -> str:
    review_prompt = read_review_section("AI_READING_PROMPT", default_review_ai_prompt())
    summary_prompt = read_summary_section("SUMMARY_PROMPT", default_summary_prompt())
    return "\n\n".join(
        [
            review_prompt,
            "总结文件分类要求如下，生成分类字段时必须服务于该分类逻辑：",
            summary_prompt,
            "输出必须是一个合法 json 对象，不要输出 Markdown 或解释文字。",
        ]
    )


def build_ai_user_prompt(
    record_payload: dict[str, str],
    fields: list[str] | None = None,
    classification_context: str = "",
) -> str:
    fields = fields or get_ai_fields()
    descriptions = get_ai_field_descriptions()
    user_prompt = read_review_section("AI_USER_PROMPT", default_ai_user_prompt())
    field_lines = [f"{field}：{descriptions.get(field, '')}".rstrip("：") for field in fields]
    classification_lines = ["", classification_context] if classification_context else []
    return "\n".join(
        [
            f"文献序号：{record_payload['index']}",
            f"标题：{record_payload['title']}",
            f"作者：{record_payload['authors']}",
            f"年份：{record_payload['year']}",
            f"期刊：{record_payload['journal']}",
            f"DOI：{record_payload['doi']}",
            f"关键词：{record_payload['keywords']}",
            f"摘要：{record_payload['abstract']}",
            *classification_lines,
            "",
            user_prompt,
            "",
            "必须输出以下 JSON 字段，字段名要完全一致：",
            *field_lines,
        ]
    )


def analysis_json_schema(fields: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {field: {"type": "string"} for field in fields},
        "required": fields,
    }


def template_signature(fields: list[str]) -> str:
    material = "\n\n".join(
        [
            read_review_section("AI_READING_PROMPT", default_review_ai_prompt()),
            read_review_section("AI_USER_PROMPT", default_ai_user_prompt()),
            read_summary_section("SUMMARY_PROMPT", default_summary_prompt()),
            get_card_template(),
            "|".join(fields),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def render_template(template: str, context: dict[str, Any]) -> str:
    rendered = template
    for key, value in context.items():
        rendered = rendered.replace("{{" + key + "}}", str(value))
    return re.sub(r"{{\s*[A-Za-z_][A-Za-z0-9_]*\s*}}", "", rendered)


def default_review_ai_prompt() -> str:
    return (
        "你是文献综述助手。"
        "请阅读 RIS 题录字段，为用户在模板中指定的研究主题生成中文文献卡片分析。"
        "不要编造题录中没有的信息；如果摘要为空，必须明确写“题录缺摘要，需阅读全文验证”。"
    )


def default_ai_user_prompt() -> str:
    return "\n".join(
        [
            "文献卡片最终会按 CARD_TEMPLATE 渲染，请生成能填入该模板的内容。",
            "请输出以下字段：",
            "broad_direction：研究大方向，适合综述目录一级分类。",
            "medium_direction：中等方向，适合综述目录二级分类。",
            "small_direction：小方向，适合综述目录三级分类。",
            "abstract_summary：1 句话概括摘要。",
            "study_object：研究对象。",
            "methods：研究方法。",
            "core_result：核心结果。",
            "research_topic_connection：和研究主题可结合的点。",
            "complexity：实验复杂性和可实现性。",
            "review_sentence：可直接放入论文综述的一句话。",
        ]
    )


def default_card_template() -> str:
    return """## {{index}}. {{title}}

literature_id:: {{literature_id}}
title:: {{title_inline}}
year:: {{year}}
doi:: {{doi}}
broad_direction:: {{broad_direction}}
medium_direction:: {{medium_direction}}
small_direction:: {{small_direction}}

- 年份：{{year}}
- 作者：{{authors}}
- 期刊：{{journal}}
- DOI：{{doi}}
- 关键词：{{keywords}}
- 摘要概括：{{abstract_summary}}
- 研究对象：{{study_object}}
- 研究方法：{{methods}}
- 核心结果：{{core_result}}
- 研究主题可结合的点：{{research_topic_connection}}
- 实验复杂性和可实现性：{{complexity}}
- 可用于论文综述的句子：{{review_sentence}}
"""


def default_summary_prompt() -> str:
    return (
        "请将文献按照研究大方向到小方向分类；分类应适合 Obsidian 总览，"
        "并能通过 Dataview 表格链接到 literature_cards.md 中对应文献卡片。"
    )


def default_summary_header_template() -> str:
    return """# 文献分类总览

> 生成时间：{{generated_at}}
> 文献数量：{{record_count}}

本文件按“研究大方向 → 中等方向 → 小方向”组织文献。每个分类下的表格由 Obsidian DataviewJS 构建，文献标题链接到 `{{cards_file}}` 中对应卡片。
"""


def default_dataview_table_template() -> str:
    return """```dataviewjs
const rows = [{{rows}}];
dv.table(
  ["文献", "年份", "作者", "期刊", "DOI"],
  rows.map(row => [dv.parse(row.link), row.year, row.authors, row.journal, row.doi])
);
```"""
