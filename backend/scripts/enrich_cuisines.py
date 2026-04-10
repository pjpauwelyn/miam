"""
enrich_cuisines.py — Batch cuisine enrichment for all recipes in the database.

Pipeline:
  1. Fetch all recipes where cuisine IS NULL (paginated, 500 at a time)
  2. Pass 1: classify_rule_based(title, ner) — write confident matches directly
  3. Pass 2: LLM fallback via CuisineClassifier.classify_batch() for unresolved rows
  4. Print a distribution report of all cuisine values after enrichment

Usage:
  # Dry-run (no DB writes, just shows what would be classified):
  python backend/scripts/enrich_cuisines.py --dry-run

  # Full run:
  python backend/scripts/enrich_cuisines.py

  # Rule-based only (skip LLM fallback):
  python backend/scripts/enrich_cuisines.py --no-llm

  # Limit to first N unclassified recipes (useful for testing):
  python backend/scripts/enrich_cuisines.py --limit 100

Requires: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env (via config.settings)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import os
from collections import Counter
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx

from config import settings
from db.connection import SupabaseREST
from services.cuisine_classifier import (
    CUISINE_VOCABULARY,
    CuisineClassifier,
    classify_rule_based,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("enrich_cuisines")

PAGE_SIZE = 500          # rows fetched per Supabase REST page
LLM_BATCH_SIZE = 20      # passed to CuisineClassifier internals
UPDATE_BATCH = 100       # number of rows updated per PATCH call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def fetch_unclassified(
    db: SupabaseREST,
    client: httpx.AsyncClient,
    limit: Optional[int] = None,
) -> list[dict]:
    """
    Fetch all recipes where cuisine IS NULL, paginated in PAGE_SIZE chunks.
    Returns list of {id, title, NER} dicts.
    """
    all_rows: list[dict] = []
    offset = 0

    while True:
        page_limit = PAGE_SIZE
        if limit is not None:
            remaining = limit - len(all_rows)
            if remaining <= 0:
                break
            page_limit = min(PAGE_SIZE, remaining)

        url = (
            f"{db.base_url}/recipes"
            f"?select=id,title,NER"
            f"&cuisine=is.null"
            f"&limit={page_limit}"
            f"&offset={offset}"
            f"&order=id.asc"
        )
        resp = await client.get(url, headers=db.headers, timeout=60.0)
        if resp.status_code != 200:
            raise RuntimeError(f"Fetch failed {resp.status_code}: {resp.text[:200]}")

        page = resp.json()
        if not page:
            break

        all_rows.extend(page)
        logger.info("Fetched %d rows (total so far: %d)", len(page), len(all_rows))

        if len(page) < page_limit:
            break  # last page
        offset += page_limit

    return all_rows


def parse_ner(raw: object) -> list[str]:
    """NER column may be a JSON string, a list, or None."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw if x]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return [str(x) for x in parsed if x] if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


async def bulk_update(
    db: SupabaseREST,
    client: httpx.AsyncClient,
    updates: list[dict],  # [{"id": ..., "cuisine": ...}, ...]
    dry_run: bool,
) -> int:
    """
    Write cuisine values back to the database.
    Uses individual PATCH per row (Supabase REST doesn't support bulk PATCH by list of IDs).
    Batched with asyncio.gather for throughput.
    Returns number of rows written.
    """
    if dry_run or not updates:
        return 0

    written = 0
    for i in range(0, len(updates), UPDATE_BATCH):
        batch = updates[i : i + UPDATE_BATCH]
        tasks = [
            db.update(
                "recipes",
                {"cuisine": row["cuisine"]},
                {"id": row["id"]},
                client=client,
            )
            for row in batch
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
        written += len(batch)
        logger.info("  Written %d / %d rows", written, len(updates))

    return written


async def fetch_distribution(db: SupabaseREST, client: httpx.AsyncClient) -> Counter:
    """Query the full cuisine distribution across all recipes."""
    url = f"{db.base_url}/recipes?select=cuisine&limit=100000"
    resp = await client.get(url, headers=db.headers, timeout=120.0)
    if resp.status_code != 200:
        logger.warning("Distribution fetch failed: %s", resp.status_code)
        return Counter()
    rows = resp.json()
    return Counter(r.get("cuisine") for r in rows)


def print_distribution(counter: Counter) -> None:
    """Pretty-print the cuisine distribution, flagging noise values."""
    total = sum(counter.values())
    vocab_set = set(CUISINE_VOCABULARY)

    print("\n" + "=" * 60)
    print(f"CUISINE DISTRIBUTION  (total recipes: {total:,})")
    print("=" * 60)

    noise: list[tuple] = []
    for cuisine, count in sorted(counter.items(), key=lambda x: -x[1]):
        pct = 100 * count / total if total else 0
        flag = ""
        if cuisine is None:
            flag = "  ⚠️  still NULL"
        elif cuisine not in vocab_set:
            flag = "  ⚠️  NOT IN VOCABULARY"
            noise.append((cuisine, count))
        print(f"  {str(cuisine):<22}  {count:>7,}  ({pct:5.1f}%){flag}")

    if noise:
        print("\nNoise values outside controlled vocabulary:")
        for v, c in noise:
            print(f"  {v!r}  ({c:,} rows)")
    else:
        print("\n✅ All classified values are within the controlled vocabulary.")
    print()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def run(
    dry_run: bool = False,
    no_llm: bool = False,
    limit: Optional[int] = None,
) -> None:
    db = SupabaseREST()
    classifier = CuisineClassifier()

    logger.info("Starting cuisine enrichment  (dry_run=%s, no_llm=%s, limit=%s)",
                dry_run, no_llm, limit)

    async with httpx.AsyncClient(timeout=60.0) as client:

        # ── Step 1: Fetch unclassified recipes ───────────────────────────
        logger.info("Step 1: Fetching unclassified recipes...")
        rows = await fetch_unclassified(db, client, limit=limit)
        logger.info("Found %d unclassified recipes.", len(rows))

        if not rows:
            logger.info("Nothing to do — all recipes already have a cuisine.")
            await _print_final_distribution(db, client)
            return

        # ── Step 2: Rule-based pass ──────────────────────────────────────
        logger.info("Step 2: Rule-based classification...")
        rule_updates: list[dict] = []
        unresolved: list[dict] = []

        for row in rows:
            title = row.get("title") or ""
            ner = parse_ner(row.get("NER"))
            cuisine = classify_rule_based(title, ner)
            if cuisine:
                rule_updates.append({"id": row["id"], "cuisine": cuisine})
            else:
                unresolved.append(row)

        rule_pct = 100 * len(rule_updates) / len(rows) if rows else 0
        logger.info(
            "Rule-based: %d / %d resolved (%.1f%%)  |  %d need LLM fallback",
            len(rule_updates), len(rows), rule_pct, len(unresolved),
        )

        if dry_run:
            logger.info("[DRY RUN] Would write %d rule-based updates.", len(rule_updates))
            # Show a sample
            for r in rule_updates[:10]:
                print(f"  {r['id']}: {r['cuisine']}")
            if len(rule_updates) > 10:
                print(f"  ... and {len(rule_updates) - 10} more")
        else:
            logger.info("Writing rule-based results to database...")
            written = await bulk_update(db, client, rule_updates, dry_run=False)
            logger.info("  ✅ Wrote %d rule-based results.", written)

        # ── Step 3: LLM fallback ─────────────────────────────────────────
        llm_updates: list[dict] = []

        if unresolved and not no_llm:
            logger.info("Step 3: LLM fallback for %d ambiguous recipes...", len(unresolved))

            # Build recipe dicts expected by CuisineClassifier
            llm_input = [
                {"title": r.get("title") or "", "NER": parse_ner(r.get("NER"))}
                for r in unresolved
            ]

            llm_results = await classifier.classify_batch(llm_input)

            for item in llm_results:
                original_row = unresolved[item["index"]]
                llm_updates.append({
                    "id": original_row["id"],
                    "cuisine": item["cuisine"],
                })

            logger.info("LLM classified %d recipes.", len(llm_updates))

            if dry_run:
                logger.info("[DRY RUN] Would write %d LLM results.", len(llm_updates))
                for r in llm_updates[:10]:
                    src_row = next(x for x in unresolved if x["id"] == r["id"])
                    print(f"  {r['id']} ({src_row.get('title', '')[:40]}): {r['cuisine']}")
                if len(llm_updates) > 10:
                    print(f"  ... and {len(llm_updates) - 10} more")
            else:
                logger.info("Writing LLM results to database...")
                written = await bulk_update(db, client, llm_updates, dry_run=False)
                logger.info("  ✅ Wrote %d LLM results.", written)

        elif unresolved and no_llm:
            logger.info(
                "Step 3: Skipped (--no-llm). %d recipes remain unclassified.",
                len(unresolved),
            )

        # ── Step 4: Distribution report ──────────────────────────────────
        logger.info("Step 4: Fetching final distribution...")
        if dry_run:
            # Show projected distribution from in-memory data
            projected = Counter(u["cuisine"] for u in rule_updates + llm_updates)
            print("\n[DRY RUN] Projected classification distribution for this batch:")
            for cuisine, count in sorted(projected.items(), key=lambda x: -x[1]):
                print(f"  {cuisine:<22}  {count:>6,}")
        else:
            dist = await fetch_distribution(db, client)
            print_distribution(dist)

    total_classified = len(rule_updates) + len(llm_updates)
    action = "Would classify" if dry_run else "Classified"
    logger.info(
        "%s %d recipes in this run (rule: %d, llm: %d).",
        action, total_classified, len(rule_updates), len(llm_updates),
    )


async def _print_final_distribution(db: SupabaseREST, client: httpx.AsyncClient) -> None:
    dist = await fetch_distribution(db, client)
    print_distribution(dist)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch-classify recipe cuisines using rule-based + LLM fallback."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the pipeline without writing to the database.",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip the LLM fallback step (rule-based only).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process only the first N unclassified recipes (for testing).",
    )
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run, no_llm=args.no_llm, limit=args.limit))


if __name__ == "__main__":
    main()
