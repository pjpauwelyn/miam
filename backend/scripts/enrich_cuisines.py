"""
enrich_cuisines.py — Batch cuisine enrichment for all recipes in the database.

Actual schema:
  recipes(recipe_id, data JSONB, source, source_tier, created_at)
  data JSONB contains at minimum: {"title": "...", "NER": [...]}
  cuisine is stored as data->>'cuisine' (JSONB field, not a top-level column)

Pipeline:
  1. Fetch all recipes where data->>'cuisine' IS NULL (paginated, 500 at a time)
  2. Pass 1: classify_rule_based(title, ner) — write confident matches directly
  3. Pass 2: LLM fallback via CuisineClassifier.classify_batch() for unresolved rows
  4. Print a distribution report of all cuisine values after enrichment

Usage (from repo root):
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

# ── Path + .env setup (must happen before any local imports) ─────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent        # backend/scripts/
BACKEND_DIR = SCRIPT_DIR.parent                     # backend/
REPO_DIR = BACKEND_DIR.parent                       # repo root

sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv

_env_path = BACKEND_DIR / ".env"
if not _env_path.exists():
    _env_path = REPO_DIR / ".env"

if _env_path.exists():
    load_dotenv(dotenv_path=_env_path, override=False)
else:
    print(
        f"WARNING: No .env found at {BACKEND_DIR / '.env'} or {REPO_DIR / '.env'}.\n"
        "Set MISTRAL_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY manually.",
        file=sys.stderr,
    )

# ── Now safe to import local modules ─────────────────────────────────────
from config import settings  # noqa: E402

import httpx  # noqa: E402

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

PAGE_SIZE = 500
UPDATE_BATCH = 100


def _headers() -> dict:
    key = (
        getattr(settings, "SUPABASE_SERVICE_ROLE_KEY", None)
        or getattr(settings, "SUPABASE_KEY", None)
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_KEY", "")
    )
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


def _base_url() -> str:
    return f"{settings.SUPABASE_URL}/rest/v1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def fetch_unclassified(
    client: httpx.AsyncClient,
    limit: Optional[int] = None,
) -> list[dict]:
    """
    Fetch recipes where data->>'cuisine' IS NULL, paginated.
    Returns list of {recipe_id, title, ner} dicts.
    """
    all_rows: list[dict] = []
    offset = 0
    base = _base_url()
    hdrs = _headers()

    while True:
        page_limit = PAGE_SIZE
        if limit is not None:
            remaining = limit - len(all_rows)
            if remaining <= 0:
                break
            page_limit = min(PAGE_SIZE, remaining)

        # PostgREST: filter on JSONB field using ->> operator
        url = (
            f"{base}/recipes"
            f"?select=recipe_id,data"
            f"&data->>cuisine=is.null"
            f"&limit={page_limit}"
            f"&offset={offset}"
            f"&order=recipe_id.asc"
        )
        resp = await client.get(url, headers=hdrs, timeout=60.0)
        if resp.status_code != 200:
            raise RuntimeError(f"Fetch failed {resp.status_code}: {resp.text[:300]}")

        page = resp.json()
        if not page:
            break

        for row in page:
            data = row.get("data") or {}
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    data = {}
            all_rows.append({
                "recipe_id": row["recipe_id"],
                "title": data.get("title") or "",
                "ner": _parse_ner(data.get("NER")),
            })

        logger.info("Fetched %d rows (total so far: %d)", len(page), len(all_rows))

        if len(page) < page_limit:
            break
        offset += page_limit

    return all_rows


def _parse_ner(raw: object) -> list[str]:
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


async def write_cuisine(
    client: httpx.AsyncClient,
    recipe_id: str,
    cuisine: str,
) -> None:
    """Call Postgres RPC to merge cuisine into data JSONB without overwriting other fields.

    Uses set_recipe_cuisine(p_id, p_cuisine) which executes:
        UPDATE recipes
        SET data = data || jsonb_build_object('cuisine', p_cuisine)
        WHERE recipe_id = p_id;
    This safely merges only the cuisine key, leaving title, NER, and all
    other fields in the JSONB blob completely intact.
    """
    url = f"{_base_url()}/rpc/set_recipe_cuisine"
    resp = await client.post(
        url,
        headers=_headers(),
        content=json.dumps({"p_id": recipe_id, "p_cuisine": cuisine}),
        timeout=30.0,
    )
    if resp.status_code not in (200, 204):
        logger.warning(
            "Update failed for %s (%s): %s",
            recipe_id, cuisine, resp.text[:100],
        )


async def bulk_write(
    client: httpx.AsyncClient,
    updates: list[dict],
    dry_run: bool,
) -> int:
    """Write cuisine updates in parallel batches. Returns rows written."""
    if dry_run or not updates:
        return 0

    written = 0
    for i in range(0, len(updates), UPDATE_BATCH):
        batch = updates[i: i + UPDATE_BATCH]
        await asyncio.gather(
            *[write_cuisine(client, u["recipe_id"], u["cuisine"]) for u in batch],
            return_exceptions=True,
        )
        written += len(batch)
        logger.info("  Written %d / %d rows", written, len(updates))
    return written


async def fetch_distribution(client: httpx.AsyncClient) -> Counter:
    """Fetch cuisine values for distribution report."""
    url = f"{_base_url()}/recipes?select=data&limit=100000"
    resp = await client.get(url, headers=_headers(), timeout=120.0)
    if resp.status_code != 200:
        logger.warning("Distribution fetch failed: %s", resp.status_code)
        return Counter()
    cuisines = []
    for row in resp.json():
        data = row.get("data") or {}
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                data = {}
        cuisines.append(data.get("cuisine"))
    return Counter(cuisines)


def print_distribution(counter: Counter) -> None:
    total = sum(counter.values())
    vocab_set = set(CUISINE_VOCABULARY)

    print("\n" + "=" * 60)
    print(f"CUISINE DISTRIBUTION  (total recipes: {total:,})")
    print("=" * 60)

    noise = []
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
    classifier = CuisineClassifier()

    logger.info(
        "Starting cuisine enrichment  (dry_run=%s, no_llm=%s, limit=%s)",
        dry_run, no_llm, limit,
    )

    async with httpx.AsyncClient(timeout=60.0) as client:

        # ── Step 1: Fetch ──────────────────────────────────────────────────────
        logger.info("Step 1: Fetching unclassified recipes...")
        rows = await fetch_unclassified(client, limit=limit)
        logger.info("Found %d unclassified recipes.", len(rows))

        if not rows:
            logger.info("Nothing to do — all recipes already have a cuisine.")
            dist = await fetch_distribution(client)
            print_distribution(dist)
            return

        # ── Step 2: Rule-based ───────────────────────────────────────────────
        logger.info("Step 2: Rule-based classification...")
        rule_updates: list[dict] = []
        unresolved: list[dict] = []

        for row in rows:
            cuisine = classify_rule_based(row["title"], row["ner"])
            if cuisine:
                rule_updates.append({"recipe_id": row["recipe_id"], "cuisine": cuisine})
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
                src = next(x for x in rows if x["recipe_id"] == r["recipe_id"])
                print(f"  {r['recipe_id']} ({src['title'][:40]}): {r['cuisine']}")
            if len(rule_updates) > 10:
                print(f"  ... and {len(rule_updates) - 10} more")
        else:
            written = await bulk_write(client, rule_updates, dry_run=False)
            logger.info("  ✅ Wrote %d rule-based results.", written)

        # ── Step 3: LLM fallback ─────────────────────────────────────────────
        llm_updates: list[dict] = []

        if unresolved and not no_llm:
            logger.info(
                "Step 3: LLM fallback for %d ambiguous recipes...", len(unresolved)
            )
            llm_input = [
                {"title": r["title"], "NER": r["ner"]} for r in unresolved
            ]
            llm_results = await classifier.classify_batch(llm_input)

            for item in llm_results:
                original = unresolved[item["index"] % len(unresolved)]
                llm_updates.append({
                    "recipe_id": original["recipe_id"],
                    "cuisine": item["cuisine"],
                })

            logger.info("LLM classified %d recipes.", len(llm_updates))

            if dry_run:
                logger.info("[DRY RUN] Sample LLM results:")
                for r in llm_updates[:10]:
                    src = next(x for x in unresolved if x["recipe_id"] == r["recipe_id"])
                    print(f"  {r['recipe_id']} ({src['title'][:40]}): {r['cuisine']}")
                if len(llm_updates) > 10:
                    print(f"  ... and {len(llm_updates) - 10} more")
            else:
                written = await bulk_write(client, llm_updates, dry_run=False)
                logger.info("  ✅ Wrote %d LLM results.", written)

        elif unresolved and no_llm:
            logger.info(
                "Step 3: Skipped (--no-llm). %d recipes remain unclassified.",
                len(unresolved),
            )

        # ── Step 4: Distribution ──────────────────────────────────────────────
        logger.info("Step 4: Distribution report...")
        if dry_run:
            projected = Counter(u["cuisine"] for u in rule_updates + llm_updates)
            print("\n[DRY RUN] Projected distribution for this batch:")
            for cuisine, count in sorted(projected.items(), key=lambda x: -x[1]):
                print(f"  {cuisine:<22}  {count:>6,}")
        else:
            dist = await fetch_distribution(client)
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
