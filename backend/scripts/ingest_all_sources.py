#!/usr/bin/env python3
"""
ingest_all_sources.py — Master ingestion for ALL recipe data sources into Supabase.

Sources:
1. RecipeNLG enriched (2000 total, ~1262 missing) → recipes_open
2. AI-generated batches (300) → recipes_open  
3. TheMealDB (598) → recipes_open
4. Curated verified (297, ~35 missing) → recipes_open
5. Fix cuisine_tags on ALL existing recipes_open rows

Also generates Mistral embeddings for all new records → embeddings_open

Usage:
    python scripts/ingest_all_sources.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import hashlib
from pathlib import Path
from uuid import uuid4, UUID
from datetime import datetime, timezone

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv
load_dotenv(BACKEND_DIR / ".env")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SERVICE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
MISTRAL_API_KEY = os.environ["MISTRAL_API_KEY"]
SUPABASE_REST = f"{SUPABASE_URL}/rest/v1"
EMBEDDING_MODEL = os.environ.get("MISTRAL_EMBED_MODEL", "mistral-embed")

HEADERS = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=minimal",
}

BATCH_SIZE = 50  # Supabase upsert batch
EMBED_BATCH = 20  # Mistral embed batch (stay under limits)

# Data paths
DATA_DIR = PROJECT_ROOT / "data"
RECIPENLG_PATH = DATA_DIR / "recipenlg_enriched_2000.jsonl"
CURATED_PATH = DATA_DIR / "curated_recipes_300.json"
BATCH_PATHS = [
    DATA_DIR / "batch_1_mediterranean_northern_eu.json",
    DATA_DIR / "batch_2_mena_east_asian.json",
    DATA_DIR / "batch_3_asian_americas_african.json",
]
THEMEALDB_PATH = DATA_DIR / "themealdb_catalog.json"
PROGRESS_PATH = DATA_DIR / "_ingest_all_progress.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def deterministic_uuid(source: str, title: str) -> str:
    """Generate a stable UUID from source + title to avoid duplicates."""
    h = hashlib.md5(f"{source}::{title}".encode()).hexdigest()
    return str(UUID(h))


def load_progress() -> dict:
    if PROGRESS_PATH.exists():
        return json.loads(PROGRESS_PATH.read_text())
    return {"ingested_ids": [], "embedded_ids": []}


def save_progress(progress: dict):
    PROGRESS_PATH.write_text(json.dumps(progress))


def supabase_upsert(table: str, rows: list[dict], client: httpx.Client) -> int:
    """Upsert rows to Supabase REST. Returns count of successful rows."""
    if not rows:
        return 0
    url = f"{SUPABASE_REST}/{table}"
    resp = client.post(url, json=rows, headers=HEADERS)
    if resp.status_code in (200, 201):
        return len(rows)
    elif resp.status_code == 409:
        # Duplicates — try one-by-one
        ok = 0
        for row in rows:
            r2 = client.post(url, json=[row], headers=HEADERS)
            if r2.status_code in (200, 201):
                ok += 1
        return ok
    else:
        logger.error(f"Upsert {table} failed: {resp.status_code} {resp.text[:300]}")
        return 0


def embed_texts(texts: list[str], client: httpx.Client) -> list[list[float]]:
    """Embed texts via Mistral API."""
    resp = client.post(
        "https://api.mistral.ai/v1/embeddings",
        json={"model": EMBEDDING_MODEL, "input": texts},
        headers={
            "Authorization": f"Bearer {MISTRAL_API_KEY}",
            "Content-Type": "application/json",
        },
        timeout=60.0,
    )
    if resp.status_code != 200:
        logger.error(f"Embed failed: {resp.status_code} {resp.text[:200]}")
        return []
    data = resp.json()
    return [item["embedding"] for item in data["data"]]


def build_embedding_text(recipe: dict) -> str:
    """Build a rich text for embedding from recipe data."""
    parts = []
    parts.append(recipe.get("title", ""))
    if recipe.get("title_en") and recipe["title_en"] != recipe.get("title"):
        parts.append(recipe["title_en"])
    if recipe.get("description"):
        parts.append(recipe["description"])
    if recipe.get("cuisine_tags"):
        parts.append(f"Cuisine: {', '.join(recipe['cuisine_tags'])}")
    if recipe.get("region_tag"):
        parts.append(f"Region: {recipe['region_tag']}")
    if recipe.get("dietary_tags"):
        parts.append(f"Dietary: {', '.join(recipe['dietary_tags'])}")
    if recipe.get("flavor_tags"):
        parts.append(f"Flavours: {', '.join(recipe['flavor_tags'])}")
    if recipe.get("course_tags"):
        parts.append(f"Course: {', '.join(recipe['course_tags'])}")
    # Ingredients
    ings = recipe.get("ingredients", [])
    if ings:
        if isinstance(ings[0], dict):
            ing_names = [i.get("name", "") for i in ings]
        else:
            ing_names = [str(i) for i in ings]
        parts.append(f"Ingredients: {', '.join(ing_names[:20])}")
    return " | ".join(filter(None, parts))


# ---------------------------------------------------------------------------
# Adapters: normalise each source to recipes_open format
# ---------------------------------------------------------------------------

def adapt_recipenlg(raw: dict) -> dict:
    """Convert enriched RecipeNLG JSONL to recipes_open data format."""
    cuisine = raw.get("_cuisine", "Unknown")
    enrichment = raw.get("_enrichment", {})
    nutrition = raw.get("_nutrition", {})

    # Parse ingredients into structured format
    raw_ings = raw.get("ingredients", [])
    if isinstance(raw_ings, str):
        raw_ings = [raw_ings]
    ingredients = []
    for ing in raw_ings:
        if isinstance(ing, str):
            ingredients.append({"name": ing, "amount": None, "unit": None})
        elif isinstance(ing, dict):
            ingredients.append(ing)

    # Parse directions into steps
    raw_dirs = raw.get("directions", [])
    if isinstance(raw_dirs, str):
        raw_dirs = [raw_dirs]
    steps = []
    for i, d in enumerate(raw_dirs):
        if isinstance(d, str):
            steps.append({"step_number": i + 1, "instruction": d})
        elif isinstance(d, dict):
            steps.append(d)

    return {
        "title": raw.get("title", "Untitled"),
        "title_en": raw.get("title", ""),
        "cuisine_tags": [cuisine] if cuisine and cuisine != "Unknown" else [],
        "region_tag": enrichment.get("region_tag"),
        "description": enrichment.get("description", ""),
        "ingredients": ingredients,
        "steps": steps,
        "time_prep_min": enrichment.get("time_prep_min"),
        "time_cook_min": enrichment.get("time_cook_min"),
        "time_total_min": enrichment.get("time_total_min"),
        "serves": enrichment.get("serves"),
        "difficulty": enrichment.get("difficulty"),
        "flavor_tags": enrichment.get("flavor_tags", []),
        "texture_tags": enrichment.get("texture_tags", []),
        "dietary_tags": raw.get("_dietary_tags", []),
        "dietary_flags": raw.get("_dietary_flags", {}),
        "nutrition_per_serving": nutrition if nutrition else None,
        "season_tags": enrichment.get("season_tags", []),
        "occasion_tags": enrichment.get("occasion_tags", []),
        "course_tags": enrichment.get("course_tags", []),
        "source_type": "recipenlg_enriched",
        "data_quality_score": raw.get("_quality_score", 0.5),
    }


def adapt_themealdb(raw: dict) -> dict:
    """Convert TheMealDB record to recipes_open data format."""
    cuisine = raw.get("cuisine", "Unknown")
    category = raw.get("category", "")

    # Parse instructions into steps
    instructions = raw.get("instructions", "")
    steps = []
    if isinstance(instructions, str):
        for i, line in enumerate(instructions.split("\n")):
            line = line.strip()
            if line and len(line) > 5:
                steps.append({"step_number": i + 1, "instruction": line})

    # Parse ingredients
    raw_ings = raw.get("ingredients", [])
    ingredients = []
    for ing in raw_ings:
        if isinstance(ing, dict):
            ingredients.append({
                "name": ing.get("name", ""),
                "amount": None,
                "unit": ing.get("measure", ""),
            })
        elif isinstance(ing, str):
            ingredients.append({"name": ing, "amount": None, "unit": None})

    # Map category to course
    course_map = {
        "Starter": ["starter"], "Side": ["side"], "Dessert": ["dessert"],
        "Breakfast": ["breakfast"], "Beef": ["main"], "Chicken": ["main"],
        "Lamb": ["main"], "Pork": ["main"], "Seafood": ["main"],
        "Pasta": ["main"], "Vegetarian": ["main"], "Vegan": ["main"],
        "Miscellaneous": [], "Goat": ["main"],
    }
    course_tags = course_map.get(category, ["main"])

    # Dietary inference
    dietary_tags = []
    if category == "Vegetarian":
        dietary_tags.append("vegetarian")
    if category == "Vegan":
        dietary_tags.extend(["vegan", "vegetarian"])

    tags_str = raw.get("tags", "")
    tag_list = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []

    return {
        "title": raw.get("title", "Untitled"),
        "title_en": raw.get("title", ""),
        "cuisine_tags": [cuisine] if cuisine else [],
        "region_tag": None,
        "description": f"{category} dish from {cuisine} cuisine." if cuisine else "",
        "ingredients": ingredients,
        "steps": steps,
        "time_prep_min": None,
        "time_cook_min": None,
        "time_total_min": None,
        "serves": None,
        "difficulty": None,
        "flavor_tags": [],
        "texture_tags": [],
        "dietary_tags": dietary_tags,
        "dietary_flags": {},
        "nutrition_per_serving": None,
        "season_tags": [],
        "occasion_tags": [],
        "course_tags": course_tags,
        "source_type": "themealdb",
        "data_quality_score": 0.6,
        "tags": tag_list,
    }


def adapt_batch_recipe(raw: dict) -> dict:
    """AI-generated batch recipes are already in the target format. Just ensure consistency."""
    data = dict(raw)
    data.setdefault("source_type", "ai_generated")
    data.setdefault("data_quality_score", 0.85)
    return data


def adapt_curated(raw: dict) -> dict:
    """Curated verified recipes are already in the target format."""
    data = dict(raw)
    data.setdefault("source_type", "curated_verified")
    data.setdefault("data_quality_score", 0.95)
    return data


# ---------------------------------------------------------------------------
# Main ingestion
# ---------------------------------------------------------------------------

def get_existing_ids(client: httpx.Client) -> set:
    """Get all existing recipe_ids from recipes_open."""
    ids = set()
    offset = 0
    while True:
        resp = client.get(
            f"{SUPABASE_REST}/recipes_open?select=recipe_id&limit=1000&offset={offset}",
            headers={k: v for k, v in HEADERS.items() if k != "Prefer"},
        )
        rows = resp.json()
        if not rows or isinstance(rows, dict):
            break
        for r in rows:
            ids.add(r["recipe_id"])
        if len(rows) < 1000:
            break
        offset += 1000
    return ids


def main():
    client = httpx.Client(timeout=60.0)
    progress = load_progress()
    existing_ids = get_existing_ids(client)
    logger.info(f"Existing recipes in DB: {len(existing_ids)}")

    all_new_recipes: list[dict] = []  # (recipe_id, data, source, source_tier)

    # -----------------------------------------------------------------------
    # 1. RecipeNLG enriched — load all 2000, skip already-ingested
    # -----------------------------------------------------------------------
    logger.info("--- Loading RecipeNLG enriched ---")
    with open(RECIPENLG_PATH) as f:
        for line in f:
            raw = json.loads(line)
            rid = deterministic_uuid("recipenlg", raw.get("title", ""))
            if rid in existing_ids:
                continue
            data = adapt_recipenlg(raw)
            data["embedding_text"] = build_embedding_text(data)
            all_new_recipes.append({
                "recipe_id": rid,
                "data": data,
                "source": "recipenlg",
                "source_tier": 2,
            })
    logger.info(f"  New RecipeNLG: {len(all_new_recipes)}")

    # -----------------------------------------------------------------------
    # 2. AI-generated batches (300)
    # -----------------------------------------------------------------------
    batch_count = 0
    for bp in BATCH_PATHS:
        logger.info(f"--- Loading {bp.name} ---")
        with open(bp) as f:
            batch = json.load(f)
        for raw in batch:
            rid = deterministic_uuid("ai_batch", raw.get("title", ""))
            if rid in existing_ids:
                continue
            data = adapt_batch_recipe(raw)
            data["embedding_text"] = build_embedding_text(data)
            all_new_recipes.append({
                "recipe_id": rid,
                "data": data,
                "source": "ai_generated",
                "source_tier": 1,
            })
            batch_count += 1
    logger.info(f"  New AI-generated: {batch_count}")

    # -----------------------------------------------------------------------
    # 3. TheMealDB (598)
    # -----------------------------------------------------------------------
    logger.info("--- Loading TheMealDB ---")
    mealdb_count = 0
    with open(THEMEALDB_PATH) as f:
        meals = json.load(f)
    for raw in meals:
        rid = deterministic_uuid("themealdb", raw.get("title", ""))
        if rid in existing_ids:
            continue
        data = adapt_themealdb(raw)
        data["embedding_text"] = build_embedding_text(data)
        all_new_recipes.append({
            "recipe_id": rid,
            "data": data,
            "source": "themealdb",
            "source_tier": 2,
        })
        mealdb_count += 1
    logger.info(f"  New TheMealDB: {mealdb_count}")

    # -----------------------------------------------------------------------
    # 4. Curated verified (missing ~35)
    # -----------------------------------------------------------------------
    logger.info("--- Loading Curated Verified ---")
    curated_count = 0
    with open(CURATED_PATH) as f:
        curated = json.load(f)
    for raw in curated:
        rid = deterministic_uuid("curated", raw.get("title", ""))
        if rid in existing_ids:
            continue
        data = adapt_curated(raw)
        data["embedding_text"] = build_embedding_text(data)
        all_new_recipes.append({
            "recipe_id": rid,
            "data": data,
            "source": "curated-verified",
            "source_tier": 0,
        })
        curated_count += 1
    logger.info(f"  New Curated: {curated_count}")

    logger.info(f"\n=== TOTAL NEW RECIPES TO INGEST: {len(all_new_recipes)} ===\n")

    # -----------------------------------------------------------------------
    # 5. Upsert all new recipes in batches
    # -----------------------------------------------------------------------
    ingested = 0
    for i in range(0, len(all_new_recipes), BATCH_SIZE):
        batch = all_new_recipes[i:i + BATCH_SIZE]
        count = supabase_upsert("recipes_open", batch, client)
        ingested += count
        logger.info(f"  Ingested {ingested}/{len(all_new_recipes)} recipes")
        time.sleep(0.2)

    logger.info(f"\n=== RECIPES INGESTED: {ingested} ===\n")

    # -----------------------------------------------------------------------
    # 6. Fix cuisine_tags on ALL existing recipes_open
    #    Some RecipeNLG records have _cuisine in enrichment but cuisine_tags=[]
    # -----------------------------------------------------------------------
    logger.info("--- Fixing cuisine_tags on existing records ---")
    fixed = 0
    offset = 0
    while True:
        resp = client.get(
            f"{SUPABASE_REST}/recipes_open?select=recipe_id,data&limit=200&offset={offset}",
            headers={k: v for k, v in HEADERS.items() if k != "Prefer"},
        )
        rows = resp.json()
        if not rows or isinstance(rows, dict):
            break

        updates = []
        for row in rows:
            d = row["data"] if isinstance(row["data"], dict) else json.loads(row["data"])
            ct = d.get("cuisine_tags", [])
            if not ct or ct == []:
                # Try to infer from _cuisine field or other data
                cuisine = d.get("_cuisine") or d.get("cuisine")
                if not cuisine and d.get("source_type") == "recipenlg_enriched":
                    # Already adapted, cuisine should be in cuisine_tags
                    pass
                if cuisine and cuisine != "Unknown":
                    d["cuisine_tags"] = [cuisine]
                    # Also build embedding_text if missing
                    if not d.get("embedding_text"):
                        d["embedding_text"] = build_embedding_text(d)
                    updates.append({
                        "recipe_id": row["recipe_id"],
                        "data": d,
                        "source": "recipenlg",  # keep original source
                        "source_tier": 2,
                    })

        if updates:
            count = supabase_upsert("recipes_open", updates, client)
            fixed += count

        if len(rows) < 200:
            break
        offset += 200

    logger.info(f"  Fixed cuisine_tags on {fixed} records")

    # -----------------------------------------------------------------------
    # 7. Generate embeddings for all new recipes
    # -----------------------------------------------------------------------
    logger.info("\n--- Generating embeddings ---")
    
    # Get IDs that already have embeddings
    existing_embed_ids = set()
    offset = 0
    while True:
        resp = client.get(
            f"{SUPABASE_REST}/embeddings_open?select=entity_id&limit=1000&offset={offset}",
            headers={k: v for k, v in HEADERS.items() if k != "Prefer"},
        )
        rows = resp.json()
        if not rows or isinstance(rows, dict):
            break
        for r in rows:
            existing_embed_ids.add(r["entity_id"])
        if len(rows) < 1000:
            break
        offset += 1000
    logger.info(f"  Existing embeddings: {len(existing_embed_ids)}")

    # Collect recipes needing embeddings
    need_embed = []
    for rec in all_new_recipes:
        if rec["recipe_id"] not in existing_embed_ids:
            need_embed.append(rec)

    logger.info(f"  Need embeddings: {len(need_embed)}")

    embedded = 0
    for i in range(0, len(need_embed), EMBED_BATCH):
        batch = need_embed[i:i + EMBED_BATCH]
        texts = []
        for rec in batch:
            d = rec["data"] if isinstance(rec["data"], dict) else json.loads(rec["data"])
            text = d.get("embedding_text") or build_embedding_text(d)
            texts.append(text[:2000])  # Truncate to stay within limits

        vectors = embed_texts(texts, client)
        if not vectors:
            logger.warning(f"  Embed batch {i} failed, retrying after 5s...")
            time.sleep(5)
            vectors = embed_texts(texts, client)
            if not vectors:
                logger.error(f"  Embed batch {i} failed permanently, skipping")
                continue

        embed_rows = []
        for j, vec in enumerate(vectors):
            embed_rows.append({
                "id": str(uuid4()),
                "entity_id": batch[j]["recipe_id"],
                "entity_type": "recipe",
                "embedding": vec,
            })

        count = supabase_upsert("embeddings_open", embed_rows, client)
        embedded += count
        logger.info(f"  Embedded {embedded}/{len(need_embed)}")
        time.sleep(0.5)  # Rate limit

    logger.info(f"\n=== EMBEDDINGS GENERATED: {embedded} ===")

    # -----------------------------------------------------------------------
    # Final summary
    # -----------------------------------------------------------------------
    # Re-count
    resp = client.head(
        f"{SUPABASE_REST}/recipes_open?select=*",
        headers={**{k: v for k, v in HEADERS.items() if k != "Prefer"}, "Prefer": "count=exact"},
    )
    total = resp.headers.get("content-range", "unknown")

    resp2 = client.head(
        f"{SUPABASE_REST}/embeddings_open?select=*",
        headers={**{k: v for k, v in HEADERS.items() if k != "Prefer"}, "Prefer": "count=exact"},
    )
    total_embed = resp2.headers.get("content-range", "unknown")

    logger.info(f"""
╔══════════════════════════════════════╗
║     INGESTION COMPLETE               ║
╠══════════════════════════════════════╣
║  New recipes ingested:  {ingested:>5}        ║
║  Cuisine tags fixed:    {fixed:>5}        ║
║  Embeddings generated:  {embedded:>5}        ║
║  Total recipes_open:    {total:>15} ║
║  Total embeddings_open: {total_embed:>15} ║
╚══════════════════════════════════════╝
""")

    client.close()


if __name__ == "__main__":
    main()
