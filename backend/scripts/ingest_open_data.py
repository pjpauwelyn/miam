#!/usr/bin/env python3
"""
ingest_open_data.py — Create Supabase tables and ingest 2,000 enriched recipes.

Steps:
1. Create recipes_open and embeddings_open tables via Supabase REST (SQL)
2. Convert enriched JSONL → RecipeDocument via OpenDataAdapter
3. Generate embeddings via Mistral Embed
4. Insert recipes + embeddings to Supabase in batches

Exception: This script calls the Mistral client directly for batch efficiency.
API key read from environment variables, never hardcoded.

Usage:
    cd backend && python ../scripts/ingest_open_data.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, BACKEND_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BACKEND_DIR, ".env"))

import httpx
from mistralai.client import Mistral

from services.adapters.open_data import OpenDataAdapter
from config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Paths
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "open")
INPUT_PATH = os.path.join(DATA_DIR, "recipenlg_enriched_2000.jsonl")
PROGRESS_PATH = os.path.join(DATA_DIR, "_ingest_progress.json")

# Supabase config
SUPABASE_URL = settings.SUPABASE_URL
SUPABASE_REST = f"{SUPABASE_URL}/rest/v1"
SERVICE_KEY = settings.SUPABASE_SERVICE_ROLE_KEY

# Batch sizes (per handoff: 50 for recipes, 25 for embeddings)
RECIPE_BATCH_SIZE = 50
EMBEDDING_BATCH_SIZE = 25
EMBEDDING_MODEL = "mistral-embed"
EMBEDDING_GEN_BATCH_SIZE = 25  # Mistral allows up to 32


def rest_headers(prefer: str = "return=minimal") -> dict[str, str]:
    return {
        "apikey": SERVICE_KEY,
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }


async def create_tables():
    """Create recipes_open and embeddings_open tables via Supabase SQL RPC."""
    # Use Supabase REST to check if tables exist first
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Check recipes_open
        resp = await client.get(
            f"{SUPABASE_REST}/recipes_open?select=recipe_id&limit=1",
            headers=rest_headers(),
        )
        if resp.status_code == 200:
            logger.info("Table recipes_open already exists")
            # Check embeddings_open
            resp2 = await client.get(
                f"{SUPABASE_REST}/embeddings_open?select=id&limit=1",
                headers=rest_headers(),
            )
            if resp2.status_code == 200:
                logger.info("Table embeddings_open already exists")
                return True

    # Tables don't exist — we need to create them via SQL
    # Since we can't run SQL directly from the sandbox, we'll try the
    # Supabase SQL endpoint (if available) or instruct the user
    logger.info("Attempting to create tables via Supabase SQL...")

    sql = """
    -- Create recipes_open table (same schema as recipes)
    CREATE TABLE IF NOT EXISTS recipes_open (
        recipe_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        data JSONB NOT NULL,
        source TEXT DEFAULT 'recipenlg',
        source_tier INTEGER DEFAULT 1,
        created_at TIMESTAMPTZ DEFAULT now()
    );

    -- Create embeddings_open table (same schema as embeddings)
    CREATE TABLE IF NOT EXISTS embeddings_open (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        entity_id UUID NOT NULL,
        entity_type TEXT DEFAULT 'recipe',
        embedding vector(1024),
        created_at TIMESTAMPTZ DEFAULT now()
    );

    -- Create index on embeddings_open
    CREATE INDEX IF NOT EXISTS idx_embeddings_open_entity
        ON embeddings_open(entity_id);
    """

    # Try via Supabase rpc endpoint
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
            headers=rest_headers(),
            json={"query": sql},
        )
        if resp.status_code in (200, 201, 204):
            logger.info("Tables created via SQL RPC")
            return True

        # Alternative: try the management API SQL endpoint
        resp = await client.post(
            f"{SUPABASE_URL}/pg/query",
            headers={
                "apikey": SERVICE_KEY,
                "Authorization": f"Bearer {SERVICE_KEY}",
                "Content-Type": "application/json",
            },
            json={"query": sql},
        )
        if resp.status_code in (200, 201):
            logger.info("Tables created via pg/query")
            return True

    logger.warning(
        "Could not create tables programmatically (status=%s). "
        "Tables may need to be created manually via Supabase dashboard.",
        resp.status_code,
    )
    return False


async def clear_tables():
    """Clear existing data from open tables before re-ingestion."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Delete all from embeddings_open first (foreign key consideration)
        resp = await client.delete(
            f"{SUPABASE_REST}/embeddings_open?id=neq.00000000-0000-0000-0000-000000000000",
            headers=rest_headers(),
        )
        logger.info("Cleared embeddings_open: %s", resp.status_code)

        # Delete all from recipes_open
        resp = await client.delete(
            f"{SUPABASE_REST}/recipes_open?recipe_id=neq.00000000-0000-0000-0000-000000000000",
            headers=rest_headers(),
        )
        logger.info("Cleared recipes_open: %s", resp.status_code)


def load_recipes(path: str) -> list[dict]:
    recipes = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                recipes.append(json.loads(line))
    return recipes


def load_progress() -> dict:
    if os.path.exists(PROGRESS_PATH):
        with open(PROGRESS_PATH, "r") as f:
            return json.load(f)
    return {"recipes_inserted": 0, "embeddings_inserted": 0, "recipe_ids": []}


def save_progress(progress: dict) -> None:
    with open(PROGRESS_PATH, "w") as f:
        json.dump(progress, f)


async def insert_recipes(recipe_rows: list[dict]) -> int:
    """Insert recipes into recipes_open. Returns number inserted."""
    total_inserted = 0
    async with httpx.AsyncClient(timeout=60.0) as client:
        for i in range(0, len(recipe_rows), RECIPE_BATCH_SIZE):
            batch = recipe_rows[i:i + RECIPE_BATCH_SIZE]
            resp = await client.post(
                f"{SUPABASE_REST}/recipes_open",
                headers=rest_headers("return=representation"),
                json=batch,
            )
            if resp.status_code in (200, 201):
                inserted = resp.json()
                total_inserted += len(inserted)
            else:
                logger.error(
                    "Recipe insert failed (batch %d): %s %s",
                    i // RECIPE_BATCH_SIZE, resp.status_code, resp.text[:200],
                )
            await asyncio.sleep(0.1)
    return total_inserted


async def insert_embeddings(embedding_rows: list[dict]) -> int:
    """Insert embeddings into embeddings_open. Returns number inserted."""
    total_inserted = 0
    async with httpx.AsyncClient(timeout=60.0) as client:
        for i in range(0, len(embedding_rows), EMBEDDING_BATCH_SIZE):
            batch = embedding_rows[i:i + EMBEDDING_BATCH_SIZE]
            resp = await client.post(
                f"{SUPABASE_REST}/embeddings_open",
                headers=rest_headers("return=minimal"),
                json=batch,
            )
            if resp.status_code in (200, 201):
                total_inserted += len(batch)
            else:
                logger.error(
                    "Embedding insert failed (batch %d): %s %s",
                    i // EMBEDDING_BATCH_SIZE, resp.status_code, resp.text[:200],
                )
            await asyncio.sleep(0.2)  # Slower for larger payloads
    return total_inserted


async def generate_embeddings_batch(
    client: Mistral,
    texts: list[str],
) -> list[list[float]]:
    """Generate embeddings for a batch of texts."""
    all_embeddings = []
    for i in range(0, len(texts), EMBEDDING_GEN_BATCH_SIZE):
        batch = texts[i:i + EMBEDDING_GEN_BATCH_SIZE]
        try:
            response = await asyncio.wait_for(
                client.embeddings.create_async(
                    model=EMBEDDING_MODEL,
                    inputs=batch,
                ),
                timeout=60.0,
            )
            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)
        except Exception as e:
            logger.error("Embedding generation failed at index %d: %s", i, e)
            # Return zero vectors for failed batch
            all_embeddings.extend([[0.0] * 1024] * len(batch))
        await asyncio.sleep(0.2)
    return all_embeddings


async def main():
    start_time = time.time()

    # Step 1: Create tables
    logger.info("Step 1: Creating tables...")
    tables_ok = await create_tables()
    if not tables_ok:
        logger.warning("Table creation may have failed — attempting ingestion anyway")

    # Step 2: Clear existing data
    logger.info("Step 2: Clearing existing data...")
    await clear_tables()

    # Step 3: Load enriched recipes
    logger.info("Step 3: Loading enriched recipes...")
    raw_recipes = load_recipes(INPUT_PATH)
    logger.info("Loaded %d enriched recipes", len(raw_recipes))

    # Step 4: Convert to RecipeDocument via OpenDataAdapter
    logger.info("Step 4: Converting to RecipeDocument...")
    adapter = OpenDataAdapter()
    recipe_docs = []
    recipe_rows = []

    for raw in raw_recipes:
        try:
            doc = adapter.adapt(raw)
            recipe_docs.append(doc)

            # Build Supabase row
            doc_dict = doc.model_dump()
            # Convert UUID to string
            doc_dict["id"] = str(doc_dict["id"])
            # Convert all nested objects to JSON-serialisable form
            recipe_rows.append({
                "recipe_id": doc_dict["id"],
                "data": json.loads(json.dumps(doc_dict, default=str)),
                "source": "recipenlg",
                "source_tier": 1,
            })
        except Exception as e:
            logger.error("Failed to convert recipe '%s': %s", raw.get("title", "?"), e)

    logger.info("Converted %d recipes to RecipeDocument", len(recipe_docs))

    # Step 5: Insert recipes
    logger.info("Step 5: Inserting recipes into recipes_open...")
    n_inserted = await insert_recipes(recipe_rows)
    logger.info("Inserted %d recipes", n_inserted)

    # Step 6: Generate embeddings
    logger.info("Step 6: Generating embeddings...")
    mistral_client = Mistral(api_key=os.environ.get("MISTRAL_API_KEY", ""))
    embedding_texts = [doc.embedding_text for doc in recipe_docs]
    embeddings = await generate_embeddings_batch(mistral_client, embedding_texts)
    logger.info("Generated %d embeddings", len(embeddings))

    # Step 7: Insert embeddings
    logger.info("Step 7: Inserting embeddings into embeddings_open...")
    embedding_rows = []
    for doc, emb in zip(recipe_docs, embeddings):
        embedding_rows.append({
            "entity_id": str(doc.id),
            "entity_type": "recipe",
            "embedding": emb,
        })

    n_emb_inserted = await insert_embeddings(embedding_rows)
    logger.info("Inserted %d embeddings", n_emb_inserted)

    elapsed = time.time() - start_time
    logger.info(
        "Done! %d recipes + %d embeddings ingested in %.1f minutes",
        n_inserted, n_emb_inserted, elapsed / 60,
    )

    # Cleanup progress file
    if os.path.exists(PROGRESS_PATH):
        os.remove(PROGRESS_PATH)


if __name__ == "__main__":
    asyncio.run(main())
