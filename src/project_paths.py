from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
EXCEL_DIR = ROOT / "output" / "excel"
MARKDOWN_DIR = ROOT / "output" / "markdown"
CACHE_DIR = ROOT / "output" / "cache"
CONFIG_DIR = ROOT / "config"

ENV_PATH = ROOT / ".env"
EXCEL_PATH = EXCEL_DIR / "literature_records.xlsx"
CARDS_PATH = MARKDOWN_DIR / "literature_cards.md"
SUMMARY_PATH = MARKDOWN_DIR / "literature_summary.md"

REQUIRED_DIRECTORIES = (RAW_DIR, EXCEL_DIR, MARKDOWN_DIR, CACHE_DIR, CONFIG_DIR)


def ensure_project_directories() -> None:
    for path in REQUIRED_DIRECTORIES:
        path.mkdir(parents=True, exist_ok=True)
