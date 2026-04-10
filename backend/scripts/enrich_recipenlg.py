#!/usr/bin/env python3
"""
enrich_recipenlg.py — Step 2 of the RecipeNLG data pipeline.

Reads recipenlg_extracted.jsonl (output of extract_recipenlg.py), applies
local enrichment (dietary inference + cuisine classification via the existing
service layer), and writes recipenlg_enriched.jsonl — the format expected by
ingest_open_data.py.

No external API calls are made for dietary inference (rule-based).
Cuisine classification uses Mistral Small via the LLM router (batched, 20/call).

Usage (from repo root):
    python backend/scripts/enrich_recipenlg.py \\
        --input  backend/data/open/recipenlg_extracted.jsonl \\
        --output backend/data/open/recipenlg_enriched_2000.jsonl

The output file is named with the record count suffix so it matches the path
already expected by ingest_open_data.py (recipenlg_enriched_2000.jsonl for
2 000-record sets). Override with --output for a different size.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone

# ── path setup ────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
BACKEND_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv
load_dotenv(BACKEND_DIR / ".env")

from services.adapters.recipe_nlg import RecipeNLGAdapter
from services.dietary_inference import DietaryInferenceEngine
from services.cuisine_classifier import CuisineClassifier
from services.embeddings import build_recipe_embedding_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# ── defaults ──────────────────────────────────────────────────────────────────
DATA_DIR = BACKEND_DIR / "data" / "open"
DEFAULT_INPUT = DATA_DIR / "recipenlg_extracted.jsonl"
DEFAULT_OUTPUT = DATA_DIR / "recipenlg_enriched_2000.jsonl"

# ── module-level singletons ───────────────────────────────────────────────────
_dietary_engine = DietaryInferenceEngine()
_cuisine_classifier = CuisineClassifier()


# ── enrichment ────────────────────────────────────────────────────────────────

def _get_ingredient_names(doc) -> list[str]:
    """Extract plain ingredient name strings from a RecipeDocument."""
    return [
        i.name if hasattr(i, "name") else i.get("name", "")
        for i in doc.ingredients
    ]


def enrich_record(raw: dict, adapter: RecipeNLGAdapter) -> dict:
    """
    Convert a raw RecipeNLG JSON object into the enriched RecipeDocument dict
    expected by OpenDataAdapter / ingest_open_data.py.

    Pipeline:
        1. RecipeNLGAdapter.adapt()   → RecipeDocument (dataclass)
        2. DietaryInferenceEngine     → dietary_flags + dietary_tags
        3. cuisine_tags               → filled in bulk by enrich() after batching
        4. build_recipe_embedding_text → embedding_text
    """
    doc = adapter.adapt(raw)
    doc_dict = doc.__dict__ if hasattr(doc, "__dict__") else dict(doc)

    ingredient_names = _get_ingredient_names(doc)

    # ── dietary inference (rule-based, synchronous) ───────────────────────────
    try:
        flags = _dietary_engine.infer_flags(ingredient_names)
        dietary_tags = _dietary_engine.dietary_tags_from_flags(flags)
        doc_dict["dietary_flags"] = flags.__dict__ if hasattr(flags, "__dict__") else dict(flags)
        doc_dict["dietary_tags"] = dietary_tags
    except Exception as exc:
        logger.debug("Dietary inference failed for '%s': %s", doc.title, exc)
        doc_dict.setdefault("dietary_flags", {})
        doc_dict.setdefault("dietary_tags", [])

    # cuisine_tags filled later via bulk classify (see enrich())
    doc_dict.setdefault("cuisine_tags", [])

    # ── embedding text ────────────────────────────────────────────────────────
    tmp = dict(doc_dict)
    tmp["ingredients"] = [{"name": n} for n in ingredient_names]
    doc_dict["embedding_text"] = build_recipe_embedding_text(tmp)

    # ── serialise nested dataclasses ─────────────────────────────────────────
    doc_dict["ingredients"] = [
        i.__dict__ if hasattr(i, "__dict__") else dict(i)
        for i in doc.ingredients
    ]
    doc_dict["steps"] = [
        s.__dict__ if hasattr(s, "__dict__") else dict(s)
        for s in doc.steps
    ]
    if hasattr(doc_dict.get("nutrition_per_serving"), "__dict__"):
        doc_dict["nutrition_per_serving"] = doc_dict["nutrition_per_serving"].__dict__

    # ── metadata ──────────────────────────────────────────────────────────────
    doc_dict.setdefault("id", str(uuid4()))
    doc_dict["source_type"] = "recipenlg"
    doc_dict["created_at"] = datetime.now(timezone.utc).isoformat()
    doc_dict["_original"] = {
        "title": raw.get("title"),
        "link": raw.get("link"),
        "source": raw.get("source"),
        "_row_index": raw.get("_row_index"),
    }

    return doc_dict


async def _classify_all(records: list[dict]) -> list[str]:
    """
    Run CuisineClassifier.classify_batch() over all records in batches.
    Returns a list of cuisine strings aligned to records by index.
    """
    # Build slim recipe dicts expected by classify_batch
    slim = [
        {
            "title": r.get("title", ""),
            "NER": [
                i.get("name", "") if isinstance(i, dict) else getattr(i, "name", "")
                for i in r.get("ingredients", [])
            ],
        }
        for r in records
    ]

    results = await _cuisine_classifier.classify_batch(slim)

    # results is [{index: int, cuisine: str}, ...] sorted by index
    cuisine_map: dict[int, str] = {item["index"]: item["cuisine"] for item in results}
    return [cuisine_map.get(i, "Other") for i in range(len(records))]


# ── main ──────────────────────────────────────────────────────────────────────

def enrich(
    input_path: Path,
    output_path: Path,
) -> int:
    if not input_path.exists():
        logger.error("Input file not found: %s", input_path)
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    adapter = RecipeNLGAdapter()
    records: list[dict] = []
    errors = 0

    logger.info("Reading %s …", input_path)
    with open(input_path, "r", encoding="utf-8") as in_file:
        for line_no, line in enumerate(in_file, 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                enriched = enrich_record(raw, adapter)
                records.append(enriched)
            except Exception as exc:
                errors += 1
                logger.warning("Line %d failed (dietary/embed): %s", line_no, exc)

    logger.info("Enriched %d records (dietary+embed). Running cuisine classification …", len(records))

    # ── bulk cuisine classification (async, batched 20/call) ──────────────────
    try:
        cuisines = asyncio.run(_classify_all(records))
        for rec, cuisine in zip(records, cuisines):
            rec["cuisine_tags"] = [cuisine] if cuisine else []
        logger.info("Cuisine classification complete.")
    except Exception as exc:
        logger.warning("Cuisine classification failed entirely, leaving cuisine_tags=[]: %s", exc)

    # ── write output ──────────────────────────────────────────────────────────
    written = 0
    with open(output_path, "w", encoding="utf-8") as out_file:
        for rec in records:
            out_file.write(json.dumps(rec, ensure_ascii=False) + "\n")
            written += 1
            if written % 500 == 0:
                logger.info("  … %d written", written)

    logger.info("Done. Written: %d | Errors: %d", written, errors)
    logger.info("Output: %s", output_path.resolve())
    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enrich extracted RecipeNLG JSONL with dietary + cuisine tags"
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Input JSONL (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output enriched JSONL (default: {DEFAULT_OUTPUT})",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    enrich(
        input_path=args.input,
        output_path=args.output,
    )
