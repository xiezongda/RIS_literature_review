from __future__ import annotations

from difflib import SequenceMatcher

from RIS_analysis import LiteratureRecord, normalize_title, unique_non_empty


def deduplicate_records(records: list[LiteratureRecord]) -> list[LiteratureRecord]:
    kept: list[LiteratureRecord] = []
    doi_index: dict[str, int] = {}

    for record in records:
        duplicate_index: int | None = None

        if record.doi and record.doi in doi_index:
            duplicate_index = doi_index[record.doi]
        else:
            duplicate_index = find_title_duplicate(record, kept)

        if duplicate_index is None:
            kept.append(record)
            if record.doi:
                doi_index[record.doi] = len(kept) - 1
        else:
            merge_records(kept[duplicate_index], record)
            if kept[duplicate_index].doi:
                doi_index[kept[duplicate_index].doi] = duplicate_index

    return kept


def find_title_duplicate(record: LiteratureRecord, kept: list[LiteratureRecord]) -> int | None:
    title_key = normalize_title(record.title)
    if not title_key:
        return None

    best_index: int | None = None
    best_score = 0.0
    for index, existing in enumerate(kept):
        if record.doi and existing.doi and record.doi != existing.doi:
            continue
        existing_key = normalize_title(existing.title)
        if not existing_key:
            continue

        score = 1.0 if title_key == existing_key else SequenceMatcher(None, title_key, existing_key).ratio()
        if score > best_score:
            best_score = score
            best_index = index

    if best_score >= 0.92:
        return best_index
    return None


def merge_records(target: LiteratureRecord, incoming: LiteratureRecord) -> None:
    target.title = choose_richer_text(target.title, incoming.title)
    target.authors = unique_non_empty([*target.authors, *incoming.authors])
    target.year = target.year or incoming.year
    target.journal = target.journal or incoming.journal
    target.doi = target.doi or incoming.doi
    target.keywords = unique_non_empty([*target.keywords, *incoming.keywords])
    target.abstract = choose_richer_text(target.abstract, incoming.abstract)
    target.source_files = unique_non_empty([*target.source_files, *incoming.source_files])
    target.duplicate_count += incoming.duplicate_count


def choose_richer_text(current: str, incoming: str) -> str:
    if not current:
        return incoming
    if not incoming:
        return current
    return incoming if len(incoming) > len(current) else current
