#!/usr/bin/env python3
"""
Enrich recipes in the Supabase `recipes_open` table that have empty cuisine_tags.
Uses classify_rule_based first (fast, no API), then CuisineClassifier.classify_batch
for any that rule_based can't resolve (uses LLM via Mistral Small).

Usage:
    cd backend
    python scripts/enrich_db_cuisines.py --dry-run    # preview without writing
    python scripts/enrich_db_cuisines.py               # actually update DB
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# ── path setup ────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
BACKEND_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv
load_dotenv(BACKEND_DIR / ".env")

import httpx

from services.cuisine_classifier import CuisineClassifier, classify_rule_based

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# ── Supabase connection ───────────────────────────────────────────────────────
SUPABASE_URL = os.environ["SUPABASE_URL"]
SERVICE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
SUPABASE_REST = f"{SUPABASE_URL}/rest/v1"

FETCH_BATCH = 100   # rows per GET page
UPDATE_BATCH = 100  # rows per PATCH batch


def _headers(prefer: str = "return=minimal") -> dict[str, str]:
    return {
        "apikey": SERVICE_KEY,
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }


# ── fetch ─────────────────────────────────────────────────────────────────────

async def fetch_empty_cuisine_recipes(client: httpx.AsyncClient) -> list[dict]:
    """
    Return all rows from recipes_open where cuisine_tags is null or [].

    Supabase REST does not support OR filters on JSONB subfields in a single
    query string, so we fetch rows where the JSONB field is either missing/null
    OR equals the literal '[]'.  We use two passes and deduplicate by recipe_id.
    """
    rows_by_id: dict[str, dict] = {}

    async def _paginate(filter_expr: str) -> None:
        offset = 0
        while True:
            url = (
                f"{SUPABASE_REST}/recipes_open"
                f"?select=recipe_id,data"
                f"&{filter_expr}"
                f"&order=recipe_id.asc"
                f"&offset={offset}&limit={FETCH_BATCH}"
            )
            resp = await client.get(url, headers=_headers("return=representation"))
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            for row in batch:
                rid = str(row["recipe_id"])
                rows_by_id[rid] = row
            offset += FETCH_BATCH
            if len(batch) < FETCH_BATCH:
                break

    # Pass 1: cuisine_tags key absent or null
    await _paginate("data->>'cuisine_tags'=is.null")
    # Pass 2: cuisine_tags is the empty JSON array string
    await _paginate("data->>'cuisine_tags'=eq.[]")

    return list(rows_by_id.values())


# ── update ────────────────────────────────────────────────────────────────────

async def patch_cuisine_tags(
    client: httpx.AsyncClient,
    updates: list[tuple[str, str]],  # [(recipe_id, cuisine), ...]
    dry_run: bool,
) -> int:
    """
    PATCH data->'cuisine_tags' for a list of (recipe_id, cuisine) pairs.
    Returns the number of rows actually updated.
    """
    if not updates:
        return 0

    if dry_run:
        for recipe_id, cuisine in updates:
            logger.info("[DRY-RUN] Would update recipe_id=%s → cuisine_tags=[%s]", recipe_id, cuisine)
        return len(updates)

    updated = 0
    for i in range(0, len(updates), UPDATE_BATCH):
        batch = updates[i : i + UPDATE_BATCH]
        for recipe_id, cuisine in batch:
            # Fetch current data blob so we can merge the new field
            get_resp = await client.get(
                f"{SUPABASE_REST}/recipes_open?select=data&recipe_id=eq.{recipe_id}",
                headers=_headers("return=representation"),
            )
            get_resp.raise_for_status()
            rows = get_resp.json()
            if not rows:
                logger.warning("recipe_id=%s not found during PATCH fetch, skipping", recipe_id)
                continue

            data = rows[0].get("data", {})
            if isinstance(data, str):
                data = json.loads(data)
            data = dict(data)
            data["cuisine_tags"] = [cuisine]

            patch_resp = await client.patch(
                f"{SUPABASE_REST}/recipes_open?recipe_id=eq.{recipe_id}",
                headers=_headers("return=minimal"),
                json={"data": data},
            )
            if patch_resp.status_code in (200, 204):
                updated += 1
            else:
                logger.error(
                    "PATCH failed for recipe_id=%s: HTTP %d — %s",
                    recipe_id, patch_resp.status_code, patch_resp.text[:200],
                )

        logger.info("Updated %d / %d so far …", updated, len(updates))

    return updated


# ── main ──────────────────────────────────────────────────────────────────────

async def run(dry_run: bool) -> None:
    logger.info("=== enrich_db_cuisines %s===", "[DRY-RUN] " if dry_run else "")

    async with httpx.AsyncClient(timeout=60.0) as client:
        # ── 1. Fetch ──────────────────────────────────────────────────────────
        logger.info("Fetching recipes with empty/null cuisine_tags …")
        rows = await fetch_empty_cuisine_recipes(client)
        total = len(rows)
        logger.info("Found %d recipes needing enrichment.", total)

        if total == 0:
            logger.info("Nothing to do — all recipes already have cuisine_tags.")
            return

        # ── 2. Rule-based pass ────────────────────────────────────────────────
        rule_updates: list[tuple[str, str]] = []
        llm_rows: list[tuple[str, dict]] = []  # (recipe_id, data_dict)

        for row in rows:
            recipe_id = str(row["recipe_id"])
            data = row.get("data", {})
            if isinstance(data, str):
                data = json.loads(data)

            title = data.get("title", "") or ""
            ner: list[str] = data.get("NER", [])
            if isinstance(ner, str):
                ner = [ner]
            # Fallback: extract names from structured ingredients list
            if not ner:
                ingredients = data.get("ingredients", [])
                ner = [
                    (i.get("name", "") if isinstance(i, dict) else str(i))
                    for i in ingredients
                ]

            cuisine = classify_rule_based(title, ner)
            if cuisine:
                rule_updates.append((recipe_id, cuisine))
            else:
                llm_rows.append((recipe_id, {"title": title, "NER": ner}))

        logger.info(
            "Rule-based resolved: %d / %d  |  Needs LLM: %d",
            len(rule_updates), total, len(llm_rows),
        )

        # ── 3. Apply rule-based updates ───────────────────────────────────────
        rule_updated = await patch_cuisine_tags(client, rule_updates, dry_run)
        logger.info("Rule-based: %d rows %s.", rule_updated, "would be updated" if dry_run else "updated")

        # ── 4. LLM fallback ───────────────────────────────────────────────────
        llm_updated = 0
        still_unresolved = 0

        if llm_rows:
            logger.info("Running LLM classification on %d unresolved recipes …", len(llm_rows))
            classifier = CuisineClassifier()
            recipe_dicts = [r for _, r in llm_rows]

            try:
                results = await classifier.classify_batch(recipe_dicts)
                # results: [{index: int, cuisine: str}, ...]
                llm_updates: list[tuple[str, str]] = []
                for item in results:
                    idx = item["index"]
                    cuisine = item.get("cuisine", "Other")
                    recipe_id = llm_rows[idx][0]
                    if cuisine and cuisine != "Other":
                        llm_updates.append((recipe_id, cuisine))
                    else:
                        still_unresolved += 1

                llm_updated = await patch_cuisine_tags(client, llm_updates, dry_run)
                logger.info(
                    "LLM: %d rows %s  |  Still unresolved (Other/no match): %d",
                    llm_updated,
                    "would be updated" if dry_run else "updated",
                    still_unresolved,
                )
            except Exception as exc:
                logger.error("LLM classification failed: %s", exc)
                still_unresolved = len(llm_rows)

    # ── 5. Summary ────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"  {'DRY-RUN ' if dry_run else ''}CUISINE ENRICHMENT SUMMARY")
    print("=" * 60)
    print(f"  Total recipes needing enrichment : {total}")
    print(f"  Rule-based resolved              : {len(rule_updates)}")
    print(f"  LLM resolved                     : {len(llm_rows) - still_unresolved}")
    print(f"  Still unresolved (Other/failed)  : {still_unresolved}")
    if dry_run:
        print("\n  [DRY-RUN] No database changes were made.")
    else:
        print(f"\n  Rows written to DB               : {rule_updated + llm_updated}")
    print("=" * 60 + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill cuisine_tags on recipes_open rows that are empty/null."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Log what would change without writing to the database.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(run(dry_run=args.dry_run))
