#!/usr/bin/env python3
"""
repair_embeddings_v2.py — Re-generate zero-vector embeddings with aggressive backoff.

Processes ONE embedding at a time with 1.5s delays to avoid Mistral 503.
Saves progress so it can be resumed.
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SERVICE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
SUPABASE_REST = f"{SUPABASE_URL}/rest/v1"
EMBEDDING_MODEL = "mistral-embed"
PROGRESS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "open", "_repair_progress.json")


def rest_headers(prefer="return=minimal"):
    return {
        "apikey": SERVICE_KEY,
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"repaired_ids": []}


def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f)


async def main():
    start = time.time()
    progress = load_progress()
    already_done = set(progress["repaired_ids"])
    
    # Step 1: Fetch ALL zero-vector embedding IDs + entity_ids
    logger.info("Finding zero-vector embeddings...")
    zero_items = []  # list of (emb_id, entity_id)
    offset = 0
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        while True:
            resp = await client.get(
                f"{SUPABASE_REST}/embeddings_open"
                f"?select=id,entity_id,embedding"
                f"&order=id.asc&offset={offset}&limit=200",
                headers=rest_headers(),
            )
            if resp.status_code != 200:
                break
            rows = resp.json()
            if not rows:
                break
            for row in rows:
                emb = row.get("embedding")
                if isinstance(emb, str):
                    try:
                        emb = json.loads(emb)
                    except:
                        cleaned = emb.strip().lstrip("[").rstrip("]")
                        emb = [float(v) for v in cleaned.split(",") if v.strip()]
                if isinstance(emb, list) and all(v == 0.0 for v in emb):
                    eid = str(row["id"])
                    if eid not in already_done:
                        zero_items.append((eid, str(row["entity_id"])))
            offset += 200
    
    logger.info("Found %d zero-vector embeddings to repair (skipping %d already done)",
                len(zero_items), len(already_done))
    
    if not zero_items:
        logger.info("Nothing to repair!")
        return
    
    # Step 2: Fetch recipe data for all entity_ids
    entity_ids = list(set(eid for _, eid in zero_items))
    recipes = {}
    async with httpx.AsyncClient(timeout=60.0) as client:
        for i in range(0, len(entity_ids), 50):
            batch = entity_ids[i:i + 50]
            ids_str = ",".join(batch)
            resp = await client.get(
                f"{SUPABASE_REST}/recipes_open?select=recipe_id,data&recipe_id=in.({ids_str})",
                headers=rest_headers(),
            )
            if resp.status_code == 200:
                for row in resp.json():
                    rid = str(row["recipe_id"])
                    data = row.get("data", {})
                    if isinstance(data, str):
                        data = json.loads(data)
                    recipes[rid] = data
    
    logger.info("Fetched %d recipes for embedding text", len(recipes))
    
    # Step 3: Generate embeddings one-by-one with retries
    mistral = Mistral(api_key=os.environ.get("MISTRAL_API_KEY", ""))
    repaired = 0
    failed = 0
    
    for idx, (emb_id, entity_id) in enumerate(zero_items):
        recipe = recipes.get(entity_id, {})
        text = recipe.get("embedding_text", "")
        if not text:
            text = f"{recipe.get('title', '')} {recipe.get('description', '')}"
        if not text.strip():
            failed += 1
            continue
        
        # Generate with retry
        new_emb = None
        for attempt in range(6):
            try:
                response = await asyncio.wait_for(
                    mistral.embeddings.create_async(
                        model=EMBEDDING_MODEL,
                        inputs=[text],
                    ),
                    timeout=30.0,
                )
                new_emb = response.data[0].embedding
                break
            except Exception as e:
                wait = min(2 ** attempt + 1.0, 30.0)
                logger.warning("Attempt %d failed: %s — waiting %.0fs", attempt + 1, str(e)[:60], wait)
                await asyncio.sleep(wait)
        
        if new_emb is None or all(v == 0.0 for v in new_emb):
            failed += 1
            if failed > 20:
                logger.error("Too many consecutive failures, stopping")
                break
            continue
        
        # Update in Supabase
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.patch(
                f"{SUPABASE_REST}/embeddings_open?id=eq.{emb_id}",
                headers=rest_headers(),
                json={"embedding": new_emb},
            )
        
        if resp.status_code in (200, 204):
            repaired += 1
            progress["repaired_ids"].append(emb_id)
            if repaired % 25 == 0:
                save_progress(progress)
                logger.info("Progress: %d/%d repaired, %d failed", repaired, len(zero_items), failed)
        else:
            logger.error("Update failed for %s: %s", emb_id, resp.status_code)
            failed += 1
        
        # Rate limit: 1.5s between calls
        await asyncio.sleep(1.5)
    
    save_progress(progress)
    elapsed = time.time() - start
    logger.info("Done: %d repaired, %d failed, %.1f minutes", repaired, failed, elapsed / 60)


if __name__ == "__main__":
    asyncio.run(main())
