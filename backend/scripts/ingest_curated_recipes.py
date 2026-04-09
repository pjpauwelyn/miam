#!/usr/bin/env python3
"""
ingest_curated_recipes.py — Ingest 297 curated recipes into Supabase.

These are research-verified, production-quality recipes that replace mock data.
They go into recipes_open + embeddings_open tables alongside RecipeNLG data.

Steps:
1. Load curated JSON
2. Convert to RecipeDocument format
3. Generate embeddings via Mistral Embed
4. Insert into Supabase (recipes_open + embeddings_open)

Exception: This script calls the Mistral client directly for batch efficiency.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from uuid import uuid4

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, BACKEND_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BACKEND_DIR, ".env"))

import httpx
from mistralai.client import Mistral

from models.recipe import (
    RecipeDocument, RecipeIngredient, RecipeStep,
    DietaryFlags, NutritionPerServing, RecipeSubstitution,
)
from services.embeddings import build_recipe_embedding_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SERVICE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
SUPABASE_REST = f"{SUPABASE_URL}/rest/v1"
INPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "curated", "all_curated_300.json")
EMBEDDING_MODEL = "mistral-embed"


def rest_headers(prefer="return=minimal"):
    return {
        "apikey": SERVICE_KEY,
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }


def build_recipe_doc(raw: dict) -> RecipeDocument:
    """Convert a curated recipe JSON to RecipeDocument."""
    ingredients = []
    for ing in raw.get("ingredients", []):
        subs = []
        for s in ing.get("substitutions", []):
            subs.append(RecipeSubstitution(
                substitute=s["substitute"],
                ratio=s["ratio"],
                notes=s.get("notes", ""),
            ))
        ingredients.append(RecipeIngredient(
            name=ing["name"],
            amount=float(ing["amount"]),
            unit=ing["unit"],
            notes=ing.get("notes"),
            is_optional=ing.get("is_optional", False),
            substitutions=subs,
        ))

    steps = []
    for st in raw.get("steps", []):
        steps.append(RecipeStep(
            step_number=st["step_number"],
            instruction=st["instruction"],
            duration_min=st.get("duration_min"),
            technique_tags=st.get("technique_tags", []),
        ))

    df = raw.get("dietary_flags", {})
    dietary_flags = DietaryFlags(**df)

    nutr = raw.get("nutrition_per_serving")
    nutrition = NutritionPerServing(**nutr) if nutr else None

    recipe_dict = {
        "title_en": raw.get("title_en", raw["title"]),
        "description": raw.get("description", ""),
        "ingredients": [{"name": ing.name} for ing in ingredients],
        "flavor_tags": raw.get("flavor_tags", []),
        "texture_tags": raw.get("texture_tags", []),
        "dietary_tags": raw.get("dietary_tags", []),
        "occasion_tags": raw.get("occasion_tags", []),
        "season_tags": raw.get("season_tags", []),
        "cuisine_tags": raw.get("cuisine_tags", []),
    }
    embedding_text = build_recipe_embedding_text(recipe_dict)

    return RecipeDocument(
        id=uuid4(),
        title=raw["title"],
        title_en=raw.get("title_en", raw["title"]),
        cuisine_tags=raw.get("cuisine_tags", []),
        region_tag=raw.get("region_tag"),
        description=raw.get("description", ""),
        ingredients=ingredients,
        steps=steps,
        time_prep_min=raw["time_prep_min"],
        time_cook_min=raw["time_cook_min"],
        time_total_min=raw.get("time_total_min", raw["time_prep_min"] + raw["time_cook_min"]),
        serves=raw["serves"],
        difficulty=raw["difficulty"],
        flavor_tags=raw.get("flavor_tags", []),
        texture_tags=raw.get("texture_tags", []),
        dietary_tags=raw.get("dietary_tags", []),
        dietary_flags=dietary_flags,
        nutrition_per_serving=nutrition,
        season_tags=raw.get("season_tags", []),
        occasion_tags=raw.get("occasion_tags", []),
        course_tags=raw.get("course_tags", []),
        image_placeholder=raw.get("image_placeholder"),
        source_type="curated-verified",
        wine_pairing_notes=raw.get("wine_pairing_notes"),
        tips=raw.get("tips", []),
        embedding_text=embedding_text,
        created_at=datetime.utcnow(),
        data_quality_score=0.98,
    )


async def generate_embedding_with_retry(
    client: Mistral, text: str, max_retries: int = 5
) -> list[float]:
    """Generate embedding with exponential backoff."""
    for attempt in range(max_retries):
        try:
            response = await asyncio.wait_for(
                client.embeddings.create_async(
                    model=EMBEDDING_MODEL, inputs=[text]
                ),
                timeout=30.0,
            )
            return response.data[0].embedding
        except Exception as e:
            wait = min(2 ** attempt + 1.0, 30.0)
            if attempt < max_retries - 1:
                logger.warning("Retry %d: %s (wait %.0fs)", attempt + 1, str(e)[:60], wait)
                await asyncio.sleep(wait)
            else:
                logger.error("All retries failed for embedding")
                return [0.0] * 1024
    return [0.0] * 1024


async def main():
    start = time.time()

    # Load curated recipes
    logger.info("Loading curated recipes...")
    with open(INPUT_PATH) as f:
        raw_recipes = json.load(f)
    logger.info("Loaded %d curated recipes", len(raw_recipes))

    # Convert to RecipeDocument
    logger.info("Converting to RecipeDocument...")
    docs = []
    for raw in raw_recipes:
        try:
            doc = build_recipe_doc(raw)
            docs.append(doc)
        except Exception as e:
            logger.error("Failed to convert '%s': %s", raw.get("title", "?"), e)

    logger.info("Converted %d recipes", len(docs))

    # Build Supabase rows
    recipe_rows = []
    for doc in docs:
        doc_dict = doc.model_dump()
        doc_dict["id"] = str(doc_dict["id"])
        recipe_rows.append({
            "recipe_id": doc_dict["id"],
            "data": json.loads(json.dumps(doc_dict, default=str)),
            "source": "curated-verified",
            "source_tier": 0,  # Tier 0 = highest quality
        })

    # Insert recipes in batches
    logger.info("Inserting %d recipes into recipes_open...", len(recipe_rows))
    async with httpx.AsyncClient(timeout=60.0) as client:
        for i in range(0, len(recipe_rows), 50):
            batch = recipe_rows[i:i + 50]
            resp = await client.post(
                f"{SUPABASE_REST}/recipes_open",
                headers=rest_headers("return=minimal"),
                json=batch,
            )
            if resp.status_code in (200, 201):
                logger.info("  Inserted batch %d (%d recipes)", i // 50 + 1, len(batch))
            else:
                logger.error("  Insert failed: %s %s", resp.status_code, resp.text[:200])
            await asyncio.sleep(0.1)

    # Generate embeddings
    logger.info("Generating embeddings...")
    mistral = Mistral(api_key=os.environ.get("MISTRAL_API_KEY", ""))
    embedding_rows = []

    for idx, doc in enumerate(docs):
        emb = await generate_embedding_with_retry(mistral, doc.embedding_text)
        embedding_rows.append({
            "entity_id": str(doc.id),
            "entity_type": "recipe",
            "embedding": emb,
        })
        if (idx + 1) % 25 == 0:
            logger.info("  Generated %d/%d embeddings", idx + 1, len(docs))
        await asyncio.sleep(1.0)  # Conservative rate limiting

    # Insert embeddings in batches
    logger.info("Inserting %d embeddings into embeddings_open...", len(embedding_rows))
    async with httpx.AsyncClient(timeout=60.0) as client:
        for i in range(0, len(embedding_rows), 25):
            batch = embedding_rows[i:i + 25]
            resp = await client.post(
                f"{SUPABASE_REST}/embeddings_open",
                headers=rest_headers("return=minimal"),
                json=batch,
            )
            if resp.status_code in (200, 201):
                logger.info("  Inserted batch %d (%d embeddings)", i // 25 + 1, len(batch))
            else:
                logger.error("  Insert failed: %s %s", resp.status_code, resp.text[:200])
            await asyncio.sleep(0.2)

    # Check for zero vectors
    zero_count = sum(1 for row in embedding_rows if all(v == 0.0 for v in row["embedding"]))
    elapsed = time.time() - start

    logger.info(
        "Done! %d recipes + %d embeddings ingested (%d zero vectors) in %.1f minutes",
        len(recipe_rows), len(embedding_rows), zero_count, elapsed / 60,
    )

    if zero_count > 0:
        logger.warning("Run repair_embeddings_v2.py to fix %d zero vectors", zero_count)


if __name__ == "__main__":
    asyncio.run(main())
