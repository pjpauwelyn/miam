#!/usr/bin/env python3
"""
enrich_recipenlg.py — Step 2 of the RecipeNLG data pipeline.

Reads recipenlg_extracted.jsonl (output of extract_recipenlg.py), applies
local enrichment (dietary inference + cuisine classification via the existing
service layer), and writes recipenlg_enriched.jsonl — the format expected by
ingest_open_data.py.

No API calls are made; all enrichment is deterministic / rule-based.

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
from services.dietary_inference import DietaryInferenceService
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


# ── enrichment ────────────────────────────────────────────────────────────────

def enrich_record(raw: dict, adapter: RecipeNLGAdapter) -> dict:
    """
    Convert a raw RecipeNLG JSON object into the enriched RecipeDocument dict
    expected by OpenDataAdapter / ingest_open_data.py.

    Pipeline:
        1. RecipeNLGAdapter.adapt()  → RecipeDocument (dataclass)
        2. DietaryInferenceService   → dietary_flags + dietary_tags
        3. CuisineClassifier         → cuisine_tags
        4. build_recipe_embedding_text → embedding_text
    """
    doc = adapter.adapt(raw)
    doc_dict = doc.__dict__ if hasattr(doc, "__dict__") else dict(doc)

    # ── dietary inference ─────────────────────────────────────────────────────
    try:
        dietary_svc = DietaryInferenceService()
        ingredient_names = [i.name if hasattr(i, "name") else i.get("name", "") for i in doc.ingredients]
        flags = dietary_svc.infer(ingredient_names)
        dietary_tags: list[str] = []
        if flags.is_vegan:
            dietary_tags.append("vegan")
        elif flags.is_vegetarian:
            dietary_tags.append("vegetarian")
        if flags.is_gluten_free:
            dietary_tags.append("gluten_free")
        if flags.is_dairy_free:
            dietary_tags.append("dairy_free")
        if flags.is_nut_free:
            dietary_tags.append("nut_free")
        doc_dict["dietary_flags"] = flags.__dict__ if hasattr(flags, "__dict__") else dict(flags)
        doc_dict["dietary_tags"] = dietary_tags
    except Exception as exc:
        logger.debug("Dietary inference failed for '%s': %s", doc.title, exc)
        doc_dict.setdefault("dietary_flags", {})
        doc_dict.setdefault("dietary_tags", [])

    # ── cuisine classification ────────────────────────────────────────────────
    try:
        classifier = CuisineClassifier()
        cuisine = classifier.classify(
            title=doc.title,
            ingredient_names=[i.name if hasattr(i, "name") else i.get("name", "") for i in doc.ingredients],
        )
        doc_dict["cuisine_tags"] = [cuisine] if cuisine else []
    except Exception as exc:
        logger.debug("Cuisine classification failed for '%s': %s", doc.title, exc)
        doc_dict.setdefault("cuisine_tags", [])

    # ── embedding text ────────────────────────────────────────────────────────
    # Temporarily serialise ingredient list for build_recipe_embedding_text
    tmp = dict(doc_dict)
    tmp["ingredients"] = [
        {"name": (i.name if hasattr(i, "name") else i.get("name", ""))}
        for i in doc.ingredients
    ]
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
    written = 0
    errors = 0

    logger.info("Enriching %s → %s", input_path, output_path)

    with (
        open(input_path, "r", encoding="utf-8") as in_file,
        open(output_path, "w", encoding="utf-8") as out_file,
    ):
        for line_no, line in enumerate(in_file, 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                enriched = enrich_record(raw, adapter)
                out_file.write(json.dumps(enriched, ensure_ascii=False) + "\n")
                written += 1
            except Exception as exc:
                errors += 1
                logger.warning("Line %d failed: %s", line_no, exc)
                continue

            if written % 500 == 0:
                logger.info("  … %d enriched", written)

    logger.info(
        "Done. Written: %d | Errors: %d", written, errors
    )
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
