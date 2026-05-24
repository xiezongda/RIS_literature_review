from __future__ import annotations

from AI_agent import load_llm_config
from AI_cache_annotation import load_env_file, prepare_runtime_annotations
from AI_group_classification import prepare_classification_scheme
from RIS_analysis import read_raw_records
from output_module import print_pipeline_summary, write_excel, write_literature_cards, write_summary
from project_paths import (
    CARDS_PATH,
    ENV_PATH,
    EXCEL_PATH,
    RAW_DIR,
    SUMMARY_PATH,
    ensure_project_directories,
)
from read_templete import get_ai_fields
from remove_duplicates import deduplicate_records


def main() -> None:
    ensure_project_directories()
    load_env_file(ENV_PATH)

    fields = get_ai_fields()
    ris_files, raw_records = read_raw_records(RAW_DIR)
    records = deduplicate_records(raw_records)
    llm_config = load_llm_config()
    classification_scheme = prepare_classification_scheme(records, fields, llm_config)
    annotations = prepare_runtime_annotations(records, fields, llm_config, classification_scheme)

    write_excel(records, EXCEL_PATH, annotations, fields)
    write_literature_cards(records, CARDS_PATH, annotations, fields)
    write_summary(records, SUMMARY_PATH, annotations, fields)
    print_pipeline_summary(ris_files, raw_records, records, annotations, fields, EXCEL_PATH, CARDS_PATH, SUMMARY_PATH)


if __name__ == "__main__":
    main()
