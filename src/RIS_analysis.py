from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


TITLE_TAGS = ("TI", "T1", "CT", "BT")
AUTHOR_TAGS = ("AU", "A1", "A2", "A3", "A4")
YEAR_TAGS = ("PY", "Y1", "Y2", "DA")
JOURNAL_TAGS = ("JO", "JF", "JA", "J1", "J2", "T2")
DOI_TAGS = ("DO",)
KEYWORD_TAGS = ("KW", "DE")
ABSTRACT_TAGS = ("AB", "N2")

RIS_LINE_RE = re.compile(r"^([A-Z0-9]{2})\s{2}-\s?(.*)$")
ENDNOTE_LINE_RE = re.compile(r"^%([A-Z0-9])\s*(.*)$")
YEAR_RE = re.compile(r"(19|20)\d{2}")
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？.!?])\s+|\n+")

ENDNOTE_TAG_MAP = {
    "0": "TY",
    "A": "AU",
    "B": "T2",
    "D": "PY",
    "J": "JO",
    "K": "KW",
    "N": "IS",
    "O": "N1",
    "P": "SP",
    "R": "DO",
    "T": "TI",
    "U": "UR",
    "V": "VL",
    "X": "AB",
    "Z": "N1",
}


@dataclass
class LiteratureRecord:
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: str = ""
    journal: str = ""
    doi: str = ""
    keywords: list[str] = field(default_factory=list)
    abstract: str = ""
    source_files: list[str] = field(default_factory=list)
    duplicate_count: int = 1


def parse_ris_file(path: Path) -> list[LiteratureRecord]:
    text = read_text_with_fallback(path)
    entries = parse_ris_entries(text)
    if not entries and looks_like_endnote_export(text):
        entries = parse_endnote_entries(text)
    return [entry_to_record(entry, path.name) for entry in entries]


def read_raw_records(raw_dir: Path) -> tuple[list[Path], list[LiteratureRecord]]:
    ris_files = sorted(raw_dir.rglob("*.ris"))
    records: list[LiteratureRecord] = []
    for ris_file in ris_files:
        records.extend(parse_ris_file(ris_file))
    return ris_files, records


def read_text_with_fallback(path: Path) -> str:
    encodings = ("utf-8-sig", "utf-8", "gb18030", "gbk", "latin-1")
    last_error: UnicodeDecodeError | None = None
    for encoding in encodings:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    return path.read_text()


def parse_ris_entries(text: str) -> list[dict[str, list[str]]]:
    entries: list[dict[str, list[str]]] = []
    current: dict[str, list[str]] = defaultdict(list)
    current_tag: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n\r")
        match = RIS_LINE_RE.match(line)
        if match:
            tag, value = match.group(1), clean_spaces(match.group(2))
            if tag == "ER":
                if current:
                    entries.append(dict(current))
                current = defaultdict(list)
                current_tag = None
                continue
            current[tag].append(value)
            current_tag = tag
        elif current_tag and line.strip():
            current[current_tag][-1] = clean_spaces(f"{current[current_tag][-1]} {line.strip()}")

    if current:
        entries.append(dict(current))

    return entries


def looks_like_endnote_export(text: str) -> bool:
    return bool(re.search(r"(?m)^%0\s+", text))


def parse_endnote_entries(text: str) -> list[dict[str, list[str]]]:
    entries: list[dict[str, list[str]]] = []
    current: dict[str, list[str]] = defaultdict(list)
    current_tag: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n\r")
        match = ENDNOTE_LINE_RE.match(line)
        if match:
            raw_tag, value = match.group(1), clean_spaces(match.group(2))
            tag = ENDNOTE_TAG_MAP.get(raw_tag, f"EN_{raw_tag}")

            if raw_tag == "0" and current:
                entries.append(dict(current))
                current = defaultdict(list)

            current[tag].append(value)
            current_tag = tag
        elif current_tag and line.strip():
            current[current_tag][-1] = clean_spaces(f"{current[current_tag][-1]} {line.strip()}")

    if current:
        entries.append(dict(current))

    return entries


def entry_to_record(entry: dict[str, list[str]], source_file: str) -> LiteratureRecord:
    return LiteratureRecord(
        title=first_value(entry, TITLE_TAGS),
        authors=unique_non_empty(values_for(entry, AUTHOR_TAGS)),
        year=extract_year(first_value(entry, YEAR_TAGS)),
        journal=first_value(entry, JOURNAL_TAGS),
        doi=normalize_doi(first_value(entry, DOI_TAGS) or find_doi_in_entry(entry)),
        keywords=split_keywords(values_for(entry, KEYWORD_TAGS)),
        abstract=join_unique(values_for(entry, ABSTRACT_TAGS)),
        source_files=[source_file],
    )


def values_for(entry: dict[str, list[str]], tags: Iterable[str]) -> list[str]:
    values: list[str] = []
    for tag in tags:
        values.extend(entry.get(tag, []))
    return [clean_spaces(value) for value in values if clean_spaces(value)]


def first_value(entry: dict[str, list[str]], tags: Iterable[str]) -> str:
    values = values_for(entry, tags)
    return values[0] if values else ""


def clean_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def join_unique(values: Iterable[str], separator: str = " ") -> str:
    return separator.join(unique_non_empty(values)).strip()


def unique_non_empty(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = clean_spaces(value)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def split_keywords(values: Iterable[str]) -> list[str]:
    parts: list[str] = []
    for value in values:
        parts.extend(re.split(r"\s*[;,；]\s*|\s{2,}", value))
    return unique_non_empty(parts)


def extract_year(value: str) -> str:
    match = YEAR_RE.search(value or "")
    return match.group(0) if match else ""


def find_doi_in_entry(entry: dict[str, list[str]]) -> str:
    for values in entry.values():
        for value in values:
            match = DOI_RE.search(value)
            if match:
                return match.group(0)
    return ""


def normalize_doi(value: str) -> str:
    if not value:
        return ""
    value = value.strip()
    match = DOI_RE.search(value)
    if match:
        value = match.group(0)
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^doi:\s*", "", value, flags=re.IGNORECASE)
    return value.strip(" .;,").lower()


def normalize_title(title: str) -> str:
    title = title.casefold()
    title = re.sub(r"[^\w\u4e00-\u9fff]+", " ", title)
    return clean_spaces(title)


def truncate(value: str, max_length: int) -> str:
    value = clean_spaces(value)
    if len(value) <= max_length:
        return value
    return value[: max_length - 1].rstrip() + "…"


def searchable_text(record: LiteratureRecord) -> str:
    return " ".join(
        [
            record.title,
            " ".join(record.keywords),
            record.abstract,
            record.journal,
        ]
    ).casefold()


def has_any(text: str, *needles: str) -> bool:
    return any(needle.casefold() in text for needle in needles)
