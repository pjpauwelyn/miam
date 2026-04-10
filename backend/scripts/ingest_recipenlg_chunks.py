#!/usr/bin/env python3
"""
ingest_recipenlg_chunks.py — Ingest the 15 pre-split RecipeNLG JSONL chunks
into Supabase (recipes_open table), with per-chunk resumability.

Each chunk contains ~79,901 lines of raw RecipeNLG records. The script:
  1. Iterates recipenlg_part_00.jsonl … recipenlg_part_14.jsonl in order.
  2. Skips chunks already marked done in _chunk_progress.json.
  3. Adapts each row via OpenDataAdapter → RecipeDocument.
  4. Inserts in batches of RECIPE_BATCH_SIZE (no embeddings — run a separate
     embedding job afterwards if needed).
  5. Writes progress after each chunk so the run can be resumed safely.

Usage (from repo root):
    python backend/scripts/ingest_recipenlg_chunks.py
    python backend/scripts/ingest_recipenlg_chunks.py --start-chunk 3
    python backend/scripts/ingest_recipenlg_chunks.py --dry-run --limit 10

Flags:
    --start-chunk N   Skip chunks 0…N-1 (default: auto from progress file)
    --limit N         Stop after inserting N recipes total (for testing)
    --dry-run         Parse and adapt without writing to Supabase
    --clear           Delete all rows from recipes_open before starting
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv
load_dotenv(BACKEND_DIR / ".env")

import httpx

from services.adapters.open_data import OpenDataAdapter
from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── paths ────────────────────────────────────────────────────────────────────
DATA_DIR = BACKEND_DIR / "data" / "open"
PROGRESS_PATH = DATA_DIR / "_chunk_progress.json"
NUM_CHUNKS = 15
CHUNK_PATTERN = "recipenlg_part_{:02d}.jsonl"

# ── supabase ─────────────────────────────────────────────────────────────────
SUPABASE_REST = f"{settings.SUPABASE_URL}/rest/v1"
SERVICE_KEY = settings.SUPABASE_SERVICE_ROLE_KEY
RECIPE_BATCH_SIZE = 200  # larger than the 2K script — table already exists


def _headers(prefer: str = "return=minimal") -> dict[str, str]:
    return {
        "apikey": SERVICE_KEY,
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }


# ── progress ─────────────────────────────────────────────────────────────────

def load_progress() -> dict:
    if PROGRESS_PATH.exists():
        with open(PROGRESS_PATH) as f:
            return json.load(f)
    return {"chunks_done": [], "total_inserted": 0}


def save_progress(progress: dict) -> None:
    with open(PROGRESS_PATH, "w") as f:
        json.dump(progress, f, indent=2)


# ── supabase helpers ─────────────────────────────────────────────────────────

async def clear_table(client: httpx.AsyncClient) -> None:
    resp = await client.delete(
        f"{SUPABASE_REST}/recipes_open"
        "?recipe_id=neq.00000000-0000-0000-0000-000000000000",
        headers=_headers(),
    )
    logger.info("Cleared recipes_open: HTTP %s", resp.status_code)


async def insert_batch(
    client: httpx.AsyncClient,
    rows: list[dict],
    dry_run: bool,
) -> int:
    if dry_run:
        return len(rows)
    resp = await client.post(
        f"{SUPABASE_REST}/recipes_open",
        headers=_headers(),
        json=rows,
        timeout=60.0,
    )
    if resp.status_code in (200, 201):
        return len(rows)
    logger.error("Insert failed: HTTP %s — %s", resp.status_code, resp.text[:300])
    return 0


# ── chunk processing ─────────────────────────────────────────────────────────

async def process_chunk(
    chunk_index: int,
    adapter: OpenDataAdapter,
    client: httpx.AsyncClient,
    dry_run: bool,
    global_limit: int | None,
    global_inserted: int,
) -> int:
    """Process one chunk file. Returns number of rows inserted."""
    path = DATA_DIR / CHUNK_PATTERN.format(chunk_index)
    if not path.exists():
        logger.warning("Chunk file not found: %s — skipping", path)
        return 0

    logger.info("── Chunk %02d: %s", chunk_index, path.name)
    chunk_inserted = 0
    batch: list[dict] = []
    parse_errors = 0
    adapt_errors = 0

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            # parse
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                parse_errors += 1
                continue

            # adapt
            try:
                doc = adapter.adapt(raw)
                doc_dict = doc.model_dump()
                doc_dict["id"] = str(doc_dict["id"])
                batch.append({
                    "recipe_id": doc_dict["id"],
                    "data": json.loads(json.dumps(doc_dict, default=str)),
                    "source": "recipenlg",
                    "source_tier": 1,
                })
            except Exception as e:
                adapt_errors += 1
                if adapt_errors <= 5:
                    logger.debug("Adapt error line %d: %s", line_no, e)
                continue

            # flush batch
            if len(batch) >= RECIPE_BATCH_SIZE:
                n = await insert_batch(client, batch, dry_run)
                chunk_inserted += n
                global_inserted += n
                batch = []
                await asyncio.sleep(0.05)

                if global_limit and global_inserted >= global_limit:
                    logger.info("Reached --limit %d, stopping.", global_limit)
                    break

            if global_limit and global_inserted >= global_limit:
                break

    # flush remainder
    if batch:
        n = await insert_batch(client, batch, dry_run)
        chunk_inserted += n

    logger.info(
        "   Chunk %02d done — inserted: %d | parse errors: %d | adapt errors: %d",
        chunk_index, chunk_inserted, parse_errors, adapt_errors,
    )
    return chunk_inserted


# ── main ─────────────────────────────────────────────────────────────────────

async def main(args: argparse.Namespace) -> None:
    start = time.time()
    progress = load_progress()

    # Determine which chunks to run
    start_chunk = args.start_chunk if args.start_chunk is not None \
        else (max(progress["chunks_done"]) + 1 if progress["chunks_done"] else 0)

    chunks_todo = [
        i for i in range(start_chunk, NUM_CHUNKS)
        if i not in progress["chunks_done"]
    ]

    if not chunks_todo:
        logger.info("All chunks already done. Use --start-chunk 0 to re-run.")
        return

    logger.info(
        "Starting ingestion | chunks to process: %s | dry_run=%s | limit=%s",
        chunks_todo, args.dry_run, args.limit,
    )

    adapter = OpenDataAdapter()
    total_inserted = progress["total_inserted"]

    async with httpx.AsyncClient(timeout=120.0) as client:
        if args.clear:
            logger.info("--clear: deleting existing rows from recipes_open…")
            await clear_table(client)
            progress = {"chunks_done": [], "total_inserted": 0}
            total_inserted = 0

        for chunk_idx in chunks_todo:
            n = await process_chunk(
                chunk_index=chunk_idx,
                adapter=adapter,
                client=client,
                dry_run=args.dry_run,
                global_limit=args.limit,
                global_inserted=total_inserted,
            )
            total_inserted += n

            if not args.dry_run:
                progress["chunks_done"].append(chunk_idx)
                progress["total_inserted"] = total_inserted
                save_progress(progress)
                logger.info(
                    "Progress saved — chunks done: %d/%d | total inserted: %d",
                    len(progress["chunks_done"]), NUM_CHUNKS, total_inserted,
                )

            if args.limit and total_inserted >= args.limit:
                break

    elapsed = time.time() - start
    logger.info(
        "=== Done: %d recipes inserted in %.1f min ===",
        total_inserted, elapsed / 60,
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest RecipeNLG chunks into Supabase")
    p.add_argument("--start-chunk", type=int, default=None,
                   help="Force start from this chunk index (0-14)")
    p.add_argument("--limit", type=int, default=None,
                   help="Stop after inserting this many recipes (for testing)")
    p.add_argument("--dry-run", action="store_true",
                   help="Parse and adapt without writing to Supabase")
    p.add_argument("--clear", action="store_true",
                   help="Delete all rows from recipes_open before starting")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
