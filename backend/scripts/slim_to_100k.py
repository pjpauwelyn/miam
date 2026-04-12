"""slim_to_100k.py — Stratified 100k recipe selection with quality scoring.

Keeps exactly 100,000 recipes from recipes_open that give the best coverage
across cuisine × course × complexity, then deletes the rest.

Strategy
--------
1. Score every row on intrinsic quality (ingredients, steps, title, NER).
2. Build strata from cuisine_tags[0] × course_tags[0].
3. Allocate seats per stratum proportionally (minority cuisines protected).
4. Within each stratum pick top-N by quality score.
5. DELETE everything not selected, then report.

Usage
-----
    python backend/scripts/slim_to_100k.py --dry-run   # preview only
    python backend/scripts/slim_to_100k.py             # live delete

Options
-------
    --target N        Number of recipes to keep (default: 100000)
    --dry-run         Print distribution report; no writes
    --min-quality N   Drop rows with quality score below N (default: 10)
    --batch-size N    DELETE batch size to avoid timeouts (default: 5000)
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import sys
import time
from collections import defaultdict

try:
    from supabase import create_client, Client
except ImportError:
    print("Install supabase-py: pip install supabase", file=sys.stderr)
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

TARGET = 100_000
MIN_QUALITY = 10
BATCH_SIZE = 5_000


# ---------------------------------------------------------------------------
# Quality scorer  (pure Python, no SQL — runs after full fetch)
# ---------------------------------------------------------------------------

def quality_score(data: dict) -> int:
    """Return 0-100 quality score for a single recipe's data JSONB."""
    score = 0

    # --- ingredients (sweet spot 5-15) ---
    ing = len(data.get("ingredients") or [])
    if 5 <= ing <= 15:
        score += 25
    elif 3 <= ing <= 20:
        score += 15
    elif ing >= 2:
        score += 5

    # --- steps (sweet spot 4-12) ---
    steps = len(data.get("steps") or [])
    if 4 <= steps <= 12:
        score += 25
    elif 2 <= steps <= 15:
        score += 15
    elif steps >= 1:
        score += 5

    # --- title length (10-60 chars is a real title) ---
    title_len = len((data.get("title") or "").strip())
    if 10 <= title_len <= 60:
        score += 20
    elif 5 <= title_len <= 80:
        score += 10

    # --- cuisine tag present and not generic ---
    cuisine_tags = data.get("cuisine_tags") or []
    if cuisine_tags:
        first = cuisine_tags[0] if isinstance(cuisine_tags, list) else ""
        if first and first not in ("Other", "Unknown", "other", ""):
            score += 20
        else:
            score += 5

    # --- NER present (richer ingredient data) ---
    ner = data.get("NER") or []
    if len(ner) > 0:
        score += 10

    return min(score, 100)


def get_stratum(data: dict) -> str:
    """cuisine_bucket::course_bucket — the stratification key."""
    cuisine_tags = data.get("cuisine_tags") or []
    course_tags = data.get("course_tags") or []

    cuisine = (
        cuisine_tags[0] if isinstance(cuisine_tags, list) and cuisine_tags else "Unknown"
    )
    course = (
        course_tags[0] if isinstance(course_tags, list) and course_tags else "unknown"
    )

    # Normalise
    if not cuisine or cuisine.lower() in ("other", "unknown", ""):
        cuisine = "Unknown"

    return f"{cuisine}::{course}"


# ---------------------------------------------------------------------------
# Allocation  (proportional with floor)
# ---------------------------------------------------------------------------

def allocate_seats(
    stratum_counts: dict[str, int],
    target: int,
    floor: int = 50,
) -> dict[str, int]:
    """Allocate target seats across strata proportionally with a minimum floor.

    Strata smaller than `floor` get all their rows (no cap needed).
    Remaining seats go to larger strata proportionally.
    """
    total = sum(stratum_counts.values())
    allocation: dict[str, int] = {}

    # Pass 1: give small strata everything they have
    leftover_target = target
    deferred: dict[str, int] = {}
    for stratum, count in stratum_counts.items():
        if count <= floor:
            allocation[stratum] = count
            leftover_target -= count
        else:
            deferred[stratum] = count

    if leftover_target <= 0 or not deferred:
        return allocation

    # Pass 2: proportional allocation for large strata
    deferred_total = sum(deferred.values())
    raw: dict[str, float] = {
        s: (c / deferred_total) * leftover_target for s, c in deferred.items()
    }

    # Floor each to int, track fractional remainder
    floored = {s: math.floor(v) for s, v in raw.items()}
    remainder = leftover_target - sum(floored.values())

    # Give remaining seats to strata with highest fractional parts
    fractions = sorted(raw.items(), key=lambda x: x[1] - math.floor(x[1]), reverse=True)
    for i, (s, _) in enumerate(fractions):
        floored[s] += 1 if i < remainder else 0

    # Cap each stratum at its actual row count
    for s, seats in floored.items():
        allocation[s] = min(seats, deferred[s])

    return allocation


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(target: int, dry_run: bool, min_quality: int, batch_size: int) -> None:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        log.error("Set SUPABASE_URL and SUPABASE_SERVICE_KEY env vars.")
        sys.exit(1)

    sb: Client = create_client(url, key)

    # ------------------------------------------------------------------
    # Step 1: Stream all recipe_id + data columns
    # ------------------------------------------------------------------
    log.info("Step 1: Fetching all rows (recipe_id + data)…")

    all_rows: list[dict] = []
    cursor = None
    page_size = 1000
    fetched = 0

    while True:
        q = (
            sb.table("recipes_open")
            .select("recipe_id, data")
            .order("recipe_id")
            .limit(page_size)
        )
        if cursor:
            q = q.gt("recipe_id", cursor)

        resp = q.execute()
        rows = resp.data or []
        if not rows:
            break

        all_rows.extend(rows)
        cursor = rows[-1]["recipe_id"]
        fetched += len(rows)

        if fetched % 50_000 == 0:
            log.info("  Fetched %d rows so far…", fetched)

    log.info("  Total rows fetched: %d", len(all_rows))

    # ------------------------------------------------------------------
    # Step 2: Score and bucket every row
    # ------------------------------------------------------------------
    log.info("Step 2: Scoring and stratifying…")

    scored: list[tuple[str, str, int]] = []  # (recipe_id, stratum, score)
    stratum_counts: dict[str, int] = defaultdict(int)

    for row in all_rows:
        data = row.get("data") or {}
        title = (data.get("title") or "").strip()
        if len(title) < 5:
            continue  # Silently drop stub titles

        sc = quality_score(data)
        if sc < min_quality:
            continue  # Drop clearly bad rows early

        stratum = get_stratum(data)
        stratum_counts[stratum] += 1
        scored.append((row["recipe_id"], stratum, sc))

    log.info("  Eligible rows (score >= %d): %d", min_quality, len(scored))

    # ------------------------------------------------------------------
    # Step 3: Allocate seats per stratum
    # ------------------------------------------------------------------
    log.info("Step 3: Allocating %d seats across %d strata…", target, len(stratum_counts))

    allocation = allocate_seats(stratum_counts, target)
    total_seats = sum(allocation.values())
    log.info("  Total seats allocated: %d", total_seats)

    # ------------------------------------------------------------------
    # Step 4: Select top-N per stratum by quality score
    # ------------------------------------------------------------------
    log.info("Step 4: Selecting best rows per stratum…")

    # Group scored rows by stratum, sort each by score DESC
    by_stratum: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for recipe_id, stratum, sc in scored:
        by_stratum[stratum].append((recipe_id, sc))

    keep_ids: set[str] = set()
    for stratum, seats in allocation.items():
        candidates = sorted(by_stratum[stratum], key=lambda x: x[1], reverse=True)
        for recipe_id, _ in candidates[:seats]:
            keep_ids.add(recipe_id)

    log.info("  Selected %d recipes to keep.", len(keep_ids))

    # ------------------------------------------------------------------
    # Step 5: Distribution report
    # ------------------------------------------------------------------
    log.info("\n%s", "=" * 70)
    log.info("STRATUM DISTRIBUTION  (top 40 strata by kept count)")
    log.info("%s", "=" * 70)
    log.info("  %-45s  %7s  %7s  %7s", "Stratum", "Total", "Eligible", "Kept")
    log.info("  %s", "-" * 68)

    kept_by_stratum: dict[str, int] = defaultdict(int)
    for recipe_id, stratum, _ in scored:
        if recipe_id in keep_ids:
            kept_by_stratum[stratum] += 1

    for stratum, kept in sorted(kept_by_stratum.items(), key=lambda x: x[1], reverse=True)[:40]:
        total_in_stratum = stratum_counts[stratum]
        log.info("  %-45s  %7d  %7d  %7d", stratum[:45], total_in_stratum, len(by_stratum[stratum]), kept)

    log.info("%s", "=" * 70)

    if dry_run:
        log.info("DRY RUN — no deletions performed.")
        log.info("Would delete %d rows, keep %d rows.", len(all_rows) - len(keep_ids), len(keep_ids))
        return

    # ------------------------------------------------------------------
    # Step 6: Delete rows NOT in keep_ids (batched)
    # ------------------------------------------------------------------
    log.info("Step 6: Deleting rows not selected…")

    all_ids = [row["recipe_id"] for row in all_rows]
    delete_ids = [rid for rid in all_ids if rid not in keep_ids]
    total_delete = len(delete_ids)
    log.info("  Will delete %d rows in batches of %d.", total_delete, batch_size)

    deleted = 0
    for i in range(0, total_delete, batch_size):
        batch = delete_ids[i : i + batch_size]
        sb.table("recipes_open").delete().in_("recipe_id", batch).execute()
        deleted += len(batch)
        if deleted % 10_000 == 0 or deleted == total_delete:
            log.info("  Deleted %d / %d rows…", deleted, total_delete)
        time.sleep(0.1)  # light backpressure

    log.info("Done. Rows kept: %d | Deleted: %d", len(keep_ids), deleted)
    log.info("Run VACUUM FULL recipes_open; in Supabase SQL Editor to reclaim disk space.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Slim recipes_open to a stratified 100k subset."
    )
    parser.add_argument("--target", type=int, default=TARGET,
                        help=f"Recipes to keep (default: {TARGET})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report only — do not delete")
    parser.add_argument("--min-quality", type=int, default=MIN_QUALITY,
                        help=f"Minimum quality score to be eligible (default: {MIN_QUALITY})")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE,
                        help=f"DELETE batch size (default: {BATCH_SIZE})")
    args = parser.parse_args()

    run(
        target=args.target,
        dry_run=args.dry_run,
        min_quality=args.min_quality,
        batch_size=args.batch_size,
    )
