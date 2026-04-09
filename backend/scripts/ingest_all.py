"""
miam Phase 0 — Full data ingestion to Supabase via REST API.
Ingests: recipes (403), embeddings (403), profiles (5).

Uses batched upserts to avoid timeouts.
All operations use service_role key for full RLS bypass.
"""
import json
import os
import sys
import time
import uuid
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOTENV_PATH = PROJECT_ROOT / "backend" / ".env"

# Load .env manually (no dependency on python-dotenv)
if DOTENV_PATH.exists():
    for line in DOTENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

SB_URL = os.environ["SUPABASE_URL"]
SB_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

HEADERS = {
    "apikey": SB_KEY,
    "Authorization": f"Bearer {SB_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates",  # upsert behaviour
}

RECIPES_PATH = PROJECT_ROOT / "data" / "recipes" / "recipes_all.json"
EMBEDDINGS_PATH = PROJECT_ROOT / "data" / "recipes" / "embeddings.json"
PROFILES_PATH = PROJECT_ROOT / "data" / "profiles" / "all_profiles.json"

BATCH_SIZE = 25  # Stay well under Supabase payload limits


def post_batch(table: str, rows: list[dict], extra_headers: dict | None = None) -> int:
    """POST a batch of rows to a Supabase REST table. Returns HTTP status."""
    url = f"{SB_URL}/rest/v1/{table}"
    hdrs = {**HEADERS}
    if extra_headers:
        hdrs.update(extra_headers)
    resp = requests.post(url, headers=hdrs, json=rows, timeout=60)
    if resp.status_code not in (200, 201):
        print(f"  ERROR {resp.status_code}: {resp.text[:300]}")
    return resp.status_code


def ingest_recipes():
    """Load recipes into the recipes table as JSONB blobs."""
    print("=" * 60)
    print("INGESTING RECIPES")
    print("=" * 60)

    recipes = json.loads(RECIPES_PATH.read_text())
    print(f"Loaded {len(recipes)} recipes from {RECIPES_PATH.name}")

    rows = []
    for r in recipes:
        # recipe_id must be a valid UUID
        rid = r.get("id", str(uuid.uuid4()))
        # Ensure it's a valid UUID string
        try:
            uuid.UUID(rid)
        except (ValueError, AttributeError):
            rid = str(uuid.uuid4())

        rows.append({
            "recipe_id": rid,
            "data": r,
            "source": r.get("source_type", "mock_tier0"),
            "source_tier": 0,
        })

    ok = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        status = post_batch("recipes", batch)
        if status in (200, 201):
            ok += len(batch)
        print(f"  Batch {i // BATCH_SIZE + 1}: {len(batch)} rows → HTTP {status} (total ok: {ok})")
        time.sleep(0.3)

    print(f"✓ Recipes ingested: {ok}/{len(rows)}")
    return ok


def ingest_embeddings():
    """Load cached embeddings into the embeddings table."""
    print()
    print("=" * 60)
    print("INGESTING EMBEDDINGS")
    print("=" * 60)

    embeddings = json.loads(EMBEDDINGS_PATH.read_text())
    print(f"Loaded {len(embeddings)} embeddings from {EMBEDDINGS_PATH.name}")

    rows = []
    for e in embeddings:
        entity_id = e["entity_id"]
        try:
            uuid.UUID(entity_id)
        except (ValueError, AttributeError):
            entity_id = str(uuid.uuid4())

        # Supabase pgvector expects the embedding as a JSON array string
        # wrapped in square brackets, formatted as text
        embedding_vec = e["embedding"]

        rows.append({
            "entity_type": e.get("entity_type", "recipe"),
            "entity_id": entity_id,
            "embedding": str(embedding_vec),  # pgvector accepts JSON array string
            "metadata": e.get("metadata", {}),
        })

    ok = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        status = post_batch("embeddings", batch,
                           extra_headers={"Prefer": "resolution=merge-duplicates,return=minimal"})
        if status in (200, 201):
            ok += len(batch)
        print(f"  Batch {i // BATCH_SIZE + 1}: {len(batch)} rows → HTTP {status} (total ok: {ok})")
        time.sleep(0.5)  # Slightly slower for vector data

    print(f"✓ Embeddings ingested: {ok}/{len(embeddings)}")
    return ok


def ingest_profiles():
    """Load test profiles into the user_profiles table."""
    print()
    print("=" * 60)
    print("INGESTING PROFILES")
    print("=" * 60)

    profiles = json.loads(PROFILES_PATH.read_text())
    print(f"Loaded {len(profiles)} profiles from {PROFILES_PATH.name}")

    rows = []
    for p in profiles:
        user_id = p.get("user_id", str(uuid.uuid4()))
        try:
            uuid.UUID(user_id)
        except (ValueError, AttributeError):
            user_id = str(uuid.uuid4())

        rows.append({
            "user_id": user_id,
            "profile_status": "complete" if p.get("onboarding_complete", False) else "onboarding",
            "profile_data": p,
        })

    ok = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        status = post_batch("user_profiles", batch)
        if status in (200, 201):
            ok += len(batch)
        print(f"  Batch {i // BATCH_SIZE + 1}: {len(batch)} rows → HTTP {status} (total ok: {ok})")

    print(f"✓ Profiles ingested: {ok}/{len(profiles)}")
    return ok


def main():
    print(f"Supabase URL: {SB_URL}")
    print(f"Service key:  ...{SB_KEY[-12:]}")
    print()

    r_ok = ingest_recipes()
    e_ok = ingest_embeddings()
    p_ok = ingest_profiles()

    print()
    print("=" * 60)
    print("INGESTION SUMMARY")
    print("=" * 60)
    print(f"  Recipes:    {r_ok}")
    print(f"  Embeddings: {e_ok}")
    print(f"  Profiles:   {p_ok}")

    if r_ok >= 300 and e_ok >= 300 and p_ok >= 5:
        print("\n✓ All data ingested successfully!")
        return 0
    else:
        print("\n✗ Some data failed to ingest — check errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
