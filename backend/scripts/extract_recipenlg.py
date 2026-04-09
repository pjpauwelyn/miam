#!/usr/bin/env python3
"""
extract_recipenlg.py — Step 1 of the RecipeNLG data pipeline.

Reads the full RecipeNLG CSV (full_dataset.csv), applies quality filters,
converts each row to a canonical RecipeDocument via RecipeNLGAdapter, and
writes the result as JSONL to data/open/recipenlg_extracted.jsonl.

This script is self-contained and requires NO API keys — it only uses the
local CSV and the in-repo adapter logic.

Usage (from repo root):
    python backend/scripts/extract_recipenlg.py \\
        --input  /path/to/full_dataset.csv \\
        --output backend/data/open/recipenlg_extracted.jsonl \\
        --limit  2000   # omit to extract everything that passes filters

Filters applied:
    - Title must be non-empty and < 200 chars
    - At least 2 NER ingredient tokens
    - At least 2 direction steps
    - No direction step longer than 2000 chars (malformed rows)
    - Deduplication on normalised title (case-folded, stripped)

Output JSONL schema (one JSON object per line):
    title          str
    ingredients    list[str]   # raw ingredient strings
    NER            list[str]   # tokenised ingredient names
    directions     list[str]
    link           str | null
    source         str | null
    _row_index     int         # original CSV row number for traceability
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# ── defaults ──────────────────────────────────────────────────────────────────
DEFAULT_OUTPUT = os.path.join(
    os.path.dirname(__file__), "..", "data", "open", "recipenlg_extracted.jsonl"
)

# ── helpers ───────────────────────────────────────────────────────────────────

def _safe_parse_list(raw: str) -> list[str]:
    """Parse a Python-literal list string from the CSV cell."""
    if not raw or not raw.strip():
        return []
    try:
        value = ast.literal_eval(raw.strip())
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
    except (ValueError, SyntaxError):
        pass
    # Fallback: treat as newline- or semicolon-separated plain text
    for sep in ("\n", ";", "|"):
        if sep in raw:
            return [v.strip() for v in raw.split(sep) if v.strip()]
    return [raw.strip()] if raw.strip() else []


def _passes_filters(
    title: str,
    ner: list[str],
    directions: list[str],
) -> bool:
    if not title or len(title) > 200:
        return False
    if len(ner) < 2:
        return False
    if len(directions) < 2:
        return False
    if any(len(step) > 2000 for step in directions):
        return False
    return True


# ── main ──────────────────────────────────────────────────────────────────────

def extract(
    input_path: str,
    output_path: str,
    limit: int | None = None,
) -> int:
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        logger.error("Input file not found: %s", input_path)
        sys.exit(1)

    seen_titles: set[str] = set()
    written = 0
    skipped_filter = 0
    skipped_dup = 0
    total_rows = 0

    logger.info("Reading %s …", input_path)

    with (
        open(input_path, "r", encoding="utf-8", errors="replace") as csv_file,
        open(output_path, "w", encoding="utf-8") as out_file,
    ):
        reader = csv.DictReader(csv_file)

        for row_index, row in enumerate(reader):
            total_rows += 1

            title = (row.get("title") or row.get("name") or "").strip()
            raw_ingredients = row.get("ingredients") or row.get("ingredient_quantities") or ""
            raw_ner = row.get("NER") or row.get("ner") or ""
            raw_directions = row.get("directions") or row.get("steps") or ""
            link = (row.get("link") or row.get("url") or "").strip() or None
            source = (row.get("source") or row.get("site") or "").strip() or None

            ingredients = _safe_parse_list(raw_ingredients)
            ner = _safe_parse_list(raw_ner)
            directions = _safe_parse_list(raw_directions)

            if not _passes_filters(title, ner, directions):
                skipped_filter += 1
                continue

            title_key = title.lower().strip()
            if title_key in seen_titles:
                skipped_dup += 1
                continue
            seen_titles.add(title_key)

            record = {
                "title": title,
                "ingredients": ingredients,
                "NER": ner,
                "directions": directions,
                "link": link,
                "source": source,
                "_row_index": row_index,
            }
            out_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            written += 1

            if written % 5000 == 0:
                logger.info(
                    "  … %d written (%.1f%% of %d rows so far)",
                    written, 100 * written / max(total_rows, 1), total_rows,
                )

            if limit and written >= limit:
                logger.info("Reached --limit %d, stopping early.", limit)
                break

    logger.info(
        "Done. Rows processed: %d | Written: %d | Skipped (filters): %d | Skipped (dups): %d",
        total_rows, written, skipped_filter, skipped_dup,
    )
    logger.info("Output: %s", output_path.resolve())
    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract and clean RecipeNLG CSV → JSONL"
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Path to full_dataset.csv",
    )
    parser.add_argument(
        "--output", "-o",
        default=DEFAULT_OUTPUT,
        help=f"Output JSONL path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--limit", "-n",
        type=int,
        default=None,
        help="Max recipes to extract (default: all passing filters)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    extract(
        input_path=args.input,
        output_path=args.output,
        limit=args.limit,
    )
