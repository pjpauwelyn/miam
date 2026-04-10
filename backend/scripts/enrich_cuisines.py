"""
enrich_cuisines.py — Batch cuisine enrichment for all recipes in the database.

Pipeline:
  1. Fetch all recipes where cuisine IS NULL (paginated, 500 at a time)
  2. Pass 1: classify_rule_based(title, ner) — write confident matches directly
  3. Pass 2: LLM fallback via CuisineClassifier.classify_batch() for unresolved rows
  4. Print a distribution report of all cuisine values after enrichment

Usage (from ANY directory):
  python backend/scripts/enrich_cuisines.py --dry-run
  python backend/scripts/enrich_cuisines.py --no-llm --limit 100
  python backend/scripts/enrich_cuisines.py

Requires: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, MISTRAL_API_KEY in backend/.env
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

# ── Path + .env setup (must happen before any local imports) ─────────────────
SCRIPT_DIR = Path(__file__).resolve().parent        # backend/scripts/
BACKEND_DIR = SCRIPT_DIR.parent                     # backend/
REPO_DIR = BACKEND_DIR.parent                       # repo root

sys.path.insert(0, str(BACKEND_DIR))

# Load .env explicitly from backend/ so this works regardless of cwd
from dotenv import load_dotenv  # python-dotenv is already a project dep

_env_path = BACKEND_DIR / ".env"
if not _env_path.exists():
    # fallback: try repo root
    _env_path = REPO_DIR / ".env"

if _env_path.exists():
    load_dotenv(dotenv_path=_env_path, override=False)
else:
    print(
        f"WARNING: No .env found at {BACKEND_DIR / '.env'} or {REPO_DIR / '.env'}.\n"
        "Set MISTRAL_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY manually.",
        file=sys.stderr,
    )

# ── Now safe to import local modules ─────────────────────────────────────────
import httpx  # noqa: E402

from config import settings  # noqa: E402
from db.connection import SupabaseREST  # noqa: E402
from services.cuisine_classifier import (  # noqa: E402
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

PAGE_SIZE = 500       # rows fetched per Supabase REST page
UPDATE_BATCH = 100    # rows updated per asyncio.gather batch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def fetch_unclassified(
    db: SupabaseREST,
    client: httpx.AsyncClient,
    limit: Optional[int] = None,
) -> list[dict]:
    """Fetch all recipes where cuisine IS NULL, paginated."""
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
            break
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
    updates: list[dict],
    dry_run: bool,
) -> int:
    """PATCH cuisine back to the DB in parallel batches. Returns rows written."""
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
    url = f"{db.base_url}/recipes?select=cuisine&limit=100000"
    resp = await client.get(url, headers=db.headers, timeout=120.0)
    if resp.status_code != 200:
        logger.warning("Distribution fetch failed: %s", resp.status_code)
        return Counter()
    return Counter(r.get("cuisine") for r in resp.json())


def print_distribution(counter: Counter) -> None:
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

    logger.info(
        "Starting cuisine enrichment  (dry_run=%s, no_llm=%s, limit=%s)",
        dry_run, no_llm, limit,
    )

    async with httpx.AsyncClient(timeout=60.0) as client:

        # ── Step 1: Fetch ────────────────────────────────────────────────
        logger.info("Step 1: Fetching unclassified recipes...")
        rows = await fetch_unclassified(db, client, limit=limit)
        logger.info("Found %d unclassified recipes.", len(rows))

        if not rows:
            logger.info("Nothing to do — all recipes already have a cuisine.")
            dist = await fetch_distribution(db, client)
            print_distribution(dist)
            return

        # ── Step 2: Rule-based ───────────────────────────────────────────
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
            logger.info("[DRY RUN] Sample rule-based results:")
            for r in rule_updates[:10]:
                print(f"  {r['id']}: {r['cuisine']}")
            if len(rule_updates) > 10:
                print(f"  ... and {len(rule_updates) - 10} more")
        else:
            written = await bulk_update(db, client, rule_updates, dry_run=False)
            logger.info("  ✅ Wrote %d rule-based results.", written)

        # ── Step 3: LLM fallback ─────────────────────────────────────────
        llm_updates: list[dict] = []

        if unresolved and not no_llm:
            logger.info("Step 3: LLM fallback for %d ambiguous recipes...", len(unresolved))

            llm_input = [
                {"title": r.get("title") or "", "NER": parse_ner(r.get("NER"))}
                for r in unresolved
            ]
            llm_results = await classifier.classify_batch(llm_input)

            for item in llm_results:
                original_row = unresolved[item["index"]]
                llm_updates.append({"id": original_row["id"], "cuisine": item["cuisine"]})

            logger.info("LLM classified %d recipes.", len(llm_updates))

            if dry_run:
                logger.info("[DRY RUN] Sample LLM results:")
                for r in llm_updates[:10]:
                    src = next(x for x in unresolved if x["id"] == r["id"])
                    print(f"  {r['id']} ({src.get('title', '')[:40]}): {r['cuisine']}")
                if len(llm_updates) > 10:
                    print(f"  ... and {len(llm_updates) - 10} more")
            else:
                written = await bulk_update(db, client, llm_updates, dry_run=False)
                logger.info("  ✅ Wrote %d LLM results.", written)

        elif unresolved and no_llm:
            logger.info(
                "Step 3: Skipped (--no-llm). %d recipes remain unclassified.",
                len(unresolved),
            )

        # ── Step 4: Distribution ─────────────────────────────────────────
        logger.info("Step 4: Distribution report...")
        if dry_run:
            projected = Counter(u["cuisine"] for u in rule_updates + llm_updates)
            print("\n[DRY RUN] Projected distribution for this batch:")
            for cuisine, count in sorted(projected.items(), key=lambda x: -x[1]):
                print(f"  {cuisine:<22}  {count:>6,}")
        else:
            dist = await fetch_distribution(db, client)
            print_distribution(dist)

    total = len(rule_updates) + len(llm_updates)
    action = "Would classify" if dry_run else "Classified"
    logger.info(
        "%s %d recipes (rule: %d, llm: %d).",
        action, total, len(rule_updates), len(llm_updates),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch-classify recipe cuisines using rule-based + LLM fallback."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Run without writing to the database.")
    parser.add_argument("--no-llm", action="store_true",
                        help="Skip LLM fallback (rule-based only).")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Process only the first N unclassified recipes.")
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run, no_llm=args.no_llm, limit=args.limit))


if __name__ == "__main__":
    main()
