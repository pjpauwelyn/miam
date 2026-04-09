"""
Embed and load recipes into PostgreSQL via Supabase REST API.

Loads all recipes from data/recipes/recipes_all.json,
generates embeddings via Mistral API, and upserts to the
recipes + embeddings tables.
"""
import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

import httpx
from mistralai.client import Mistral

# Configuration
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RECIPES_PATH = PROJECT_ROOT / "data" / "recipes" / "recipes_all.json"

sys.path.insert(0, str(PROJECT_ROOT / "backend"))
from config import settings

EMBEDDING_MODEL = "mistral-embed"
EMBEDDING_DIM = 1024
BATCH_SIZE = 25  # Mistral allows up to ~32 per batch


def get_supabase_headers():
    key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_ANON_KEY
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


async def embed_batch(client: Mistral, texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts via Mistral."""
    response = await client.embeddings.create_async(
        model=EMBEDDING_MODEL,
        inputs=texts,
    )
    return [item.embedding for item in response.data]


async def upsert_recipes(recipes: list[dict], headers: dict):
    """Insert recipes into the recipes table."""
    base_url = f"{settings.SUPABASE_URL}/rest/v1"

    rows = []
    for r in recipes:
        recipe_id = r.get("id", str(uuid4()))
        rows.append({
            "recipe_id": recipe_id,
            "data": r,
            "source": r.get("source_type", "mock_tier0"),
            "source_tier": 0,
        })

    # Insert in chunks of 50
    async with httpx.AsyncClient() as client:
        for i in range(0, len(rows), 50):
            chunk = rows[i:i+50]
            # Use upsert to handle duplicates
            upsert_headers = {**headers, "Prefer": "resolution=merge-duplicates,return=minimal"}
            resp = await client.post(
                f"{base_url}/recipes",
                headers=upsert_headers,
                json=chunk,
                timeout=30.0,
            )
            if resp.status_code not in (200, 201):
                print(f"  Warning: Recipe upsert batch {i}-{i+len(chunk)} returned {resp.status_code}: {resp.text[:200]}")
            else:
                print(f"  Recipes batch {i}-{i+len(chunk)} upserted")


async def upsert_embeddings(embeddings_data: list[dict], headers: dict):
    """Insert embeddings into the embeddings table."""
    base_url = f"{settings.SUPABASE_URL}/rest/v1"

    async with httpx.AsyncClient() as client:
        for i in range(0, len(embeddings_data), 25):
            chunk = embeddings_data[i:i+25]
            resp = await client.post(
                f"{base_url}/embeddings",
                headers=headers,
                json=chunk,
                timeout=60.0,
            )
            if resp.status_code not in (200, 201):
                print(f"  Warning: Embedding batch {i}-{i+len(chunk)} returned {resp.status_code}: {resp.text[:200]}")
            else:
                print(f"  Embeddings batch {i}-{i+len(chunk)} upserted")


async def main():
    # Load recipes
    print(f"Loading recipes from {RECIPES_PATH}...")
    if not RECIPES_PATH.exists():
        print(f"ERROR: {RECIPES_PATH} not found. Run generate_recipes.py first.")
        sys.exit(1)

    with open(RECIPES_PATH, "r", encoding="utf-8") as f:
        recipes = json.load(f)

    print(f"Loaded {len(recipes)} recipes")

    # Initialize Mistral client
    mistral = Mistral(api_key=settings.MISTRAL_API_KEY)
    headers = get_supabase_headers()

    # Step 1: Insert recipe documents
    print("\nStep 1: Upserting recipe documents...")
    await upsert_recipes(recipes, headers)

    # Step 2: Generate embeddings
    print("\nStep 2: Generating embeddings...")
    all_embedding_rows = []

    for batch_start in range(0, len(recipes), BATCH_SIZE):
        batch = recipes[batch_start:batch_start + BATCH_SIZE]

        # Build embedding texts
        texts = []
        recipe_ids = []
        for r in batch:
            emb_text = r.get("embedding_text", "")
            if not emb_text:
                # Fallback: build from fields
                parts = [
                    r.get("title", ""),
                    r.get("description", ""),
                    " ".join(i.get("name", "") for i in r.get("ingredients", []) if isinstance(i, dict)),
                    " ".join(r.get("flavor_tags", [])),
                    " ".join(r.get("cuisine_tags", [])),
                ]
                emb_text = " ".join(filter(None, parts))
            texts.append(emb_text)
            recipe_ids.append(r.get("id", str(uuid4())))

        # Embed batch
        try:
            embeddings = await embed_batch(mistral, texts)

            for j, emb in enumerate(embeddings):
                all_embedding_rows.append({
                    "id": str(uuid4()),
                    "entity_type": "recipe",
                    "entity_id": recipe_ids[j],
                    "embedding": str(emb),  # Supabase expects vector as string
                    "metadata": json.dumps({"title": batch[j].get("title", "")}),
                })

            print(f"  Embedded batch {batch_start}-{batch_start + len(batch)} ({len(all_embedding_rows)} total)")

        except Exception as e:
            print(f"  ERROR embedding batch {batch_start}: {e}")
            continue

    # Step 3: Insert embeddings
    print(f"\nStep 3: Upserting {len(all_embedding_rows)} embeddings...")
    await upsert_embeddings(all_embedding_rows, headers)

    # Step 4: Verify
    print("\nStep 4: Verifying...")
    async with httpx.AsyncClient() as client:
        # Count recipes
        resp = await client.get(
            f"{settings.SUPABASE_URL}/rest/v1/recipes?select=recipe_id",
            headers={**headers, "Prefer": "count=exact"},
            timeout=30.0,
        )
        recipe_count = len(resp.json()) if resp.status_code == 200 else 0

        # Count embeddings
        resp = await client.get(
            f"{settings.SUPABASE_URL}/rest/v1/embeddings?select=id&entity_type=eq.recipe",
            headers={**headers, "Prefer": "count=exact"},
            timeout=30.0,
        )
        emb_count = len(resp.json()) if resp.status_code == 200 else 0

    print(f"\nResults:")
    print(f"  Recipes in DB: {recipe_count}")
    print(f"  Embeddings in DB: {emb_count}")
    print(f"  Expected: ~{len(recipes)}")

    if recipe_count >= len(recipes) * 0.9 and emb_count >= len(recipes) * 0.9:
        print("\nIngestion SUCCESS")
    else:
        print("\nIngestion PARTIAL — check logs above for errors")


if __name__ == "__main__":
    asyncio.run(main())
