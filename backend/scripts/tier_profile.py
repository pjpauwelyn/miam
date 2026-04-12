"""tier_profile.py — Deterministic Tier-1 profiler for recipes_open.

Usage:
    python tier_profile.py [--batch-size N] [--dry-run] [--limit N]

What it does:
    1. Reads recipes_open in batches (cursor-based, restartable).
    2. Evaluates each record against Tier-1 / Tier-2 / Tier-3 criteria.
    3. Writes back: tier, tier_assigned_at, enrichment_flags, enrichment_status.
    4. On first touch, seeds a minimal provenance stub so the column is never {}.
    5. Never modifies the data JSONB column.
    6. Is fully idempotent — safe to re-run at any time.

Tier definitions (canonical source: docs/SCHEMA_CONTRACT.md):
    Tier 1 — RAG-ready:
        - title present and length >= 5 chars
        - ingredient_count >= 2  (computed column)
        - step_count >= 2        (computed column)
        - description present, not a stub, length >= 80 chars
        - cuisine_tags non-empty (data->>'cuisine_tags' != '[]')
        - course_tags non-empty   ← REQUIRED (added 2026-04-12)
        - enrichment_status IN ('deterministic_enriched','llm_enriched','validated')

    Tier 2 — Usable, incomplete:
        - title present
        - ingredient_count >= 2
        - step_count >= 1
        - (does NOT meet Tier 1)

    Tier 3 — Skeleton:
        - title present
        - (does NOT meet Tier 2)

    Tier 0 — Untiered / rejected:
        - no usable title, or enrichment_status = 'rejected'
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

try:
    from supabase import create_client, Client
except ImportError:
    print("Install supabase-py: pip install supabase", file=sys.stderr)
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier criteria
# ---------------------------------------------------------------------------

def _is_stub_description(desc: str | None) -> bool:
    """Returns True if description looks like a generated stub."""
    if not desc:
        return True
    desc = desc.strip()
    if len(desc) < 80:
        return True
    stub_patterns = [
        "a recipe for",
        "this is a recipe",
        "delicious recipe",
        "simple recipe",
    ]
    lower = desc.lower()
    return any(lower.startswith(p) for p in stub_patterns)


def _non_empty_array(val: Any) -> bool:
    """True if val is a non-empty JSON array (list or JSON string)."""
    if isinstance(val, list):
        return len(val) > 0
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return isinstance(parsed, list) and len(parsed) > 0
        except (json.JSONDecodeError, TypeError):
            return False
    return False


def assign_tier(row: dict) -> tuple[int, dict, str, dict | None]:
    """Assign tier to a row from recipes_open.

    Returns:
        (tier_int, enrichment_flags_dict, updated_enrichment_status,
         provenance_stub_or_none)

    provenance_stub_or_none is non-None only when the row has an empty provenance
    column, so the caller can seed a minimal stub on first touch.
    """
    data: dict = row.get("data") or {}
    status: str = row.get("enrichment_status", "raw")
    existing_provenance: dict = row.get("provenance") or {}

    # Fast-reject
    if status == "rejected":
        flags = _build_flags(data, row)
        return 0, flags, "rejected", None

    title: str = (data.get("title") or "").strip()
    description: str | None = data.get("description")
    cuisine_tags = data.get("cuisine_tags", [])
    course_tags = data.get("course_tags", [])
    ingredient_count: int = row.get("ingredient_count") or 0
    step_count: int = row.get("step_count") or 0

    flags = _build_flags(data, row)

    # --- Tier 1 ---
    tier1 = (
        len(title) >= 5
        and ingredient_count >= 2
        and step_count >= 2
        and not _is_stub_description(description)
        and _non_empty_array(cuisine_tags)
        and _non_empty_array(course_tags)      # required since 2026-04-12
        and status in ("deterministic_enriched", "llm_enriched", "validated")
    )
    if tier1:
        new_status = "validated" if status != "validated" else status
        provenance_stub = _maybe_seed_provenance(existing_provenance, data)
        return 1, flags, new_status, provenance_stub

    # --- Tier 2 ---
    tier2 = len(title) >= 3 and ingredient_count >= 2 and step_count >= 1
    if tier2:
        provenance_stub = _maybe_seed_provenance(existing_provenance, data)
        return 2, flags, status, provenance_stub

    # --- Tier 3 ---
    if len(title) >= 1:
        provenance_stub = _maybe_seed_provenance(existing_provenance, data)
        return 3, flags, status, provenance_stub

    # --- Untiered ---
    return 0, flags, status, None


def _build_flags(data: dict, row: dict) -> dict:
    """Build enrichment_flags from current data state.

    Every flag that is a hard Tier-1 criterion must be listed here so the
    pipeline dashboard can show exactly which criterion blocks promotion.
    """
    description = data.get("description") or ""
    existing_flags: dict = row.get("enrichment_flags") or {}
    return {
        "has_parsed_ingredients": (row.get("ingredient_count") or 0) >= 1,
        "has_normalised_units": _has_normalised_units(data),
        "has_dietary_flags": _has_dietary_flags(data),
        "has_cuisine_tag": _non_empty_array(data.get("cuisine_tags", [])),
        "has_course_tag": _non_empty_array(data.get("course_tags", [])),  # Tier-1 criterion
        "has_real_description": not _is_stub_description(description),
        "has_llm_flavor_tags": _non_empty_array(data.get("flavor_tags", [])),
        "has_nutrition": data.get("nutrition_per_serving") is not None,
        # Preserve embedding flag and version — only repair_embeddings_v2.py may change them
        "has_embedding": existing_flags.get("has_embedding", False),
        "rag_embedding_version": existing_flags.get("rag_embedding_version"),
    }


def _has_normalised_units(data: dict) -> bool:
    METRIC_UNITS = {"g", "ml", "dl", "cl", "kg", "l",
                    "tbsp", "tsp", "piece", "pinch", "bunch", "to-taste"}
    ingredients = data.get("ingredients") or []
    if not ingredients:
        return False
    return any(i.get("unit", "").lower() in METRIC_UNITS for i in ingredients)


def _has_dietary_flags(data: dict) -> bool:
    flags = data.get("dietary_flags") or {}
    # Consider enriched if any flag is explicitly True (not just all-False default)
    return any(bool(v) for v in flags.values())


def _maybe_seed_provenance(existing: dict, data: dict) -> dict | None:
    """Return a minimal provenance stub if the record has never been touched.

    The stub records the source as 'recipenlg_raw' for CAT-A fields and
    'unknown' for all enrichable groups.  Enrichment scripts will overwrite
    individual keys as they run.  This prevents the provenance column from
    remaining '{}' indefinitely, which makes observability queries unreliable.

    Returns None if the record already has any provenance keys set.
    """
    if existing:  # already seeded — don't touch
        return None

    now = datetime.now(timezone.utc).isoformat()
    stub: dict = {
        "title":               {"source": "recipenlg_raw",   "confidence": 0.5,  "method": "ingest", "enriched_at": now},
        "description":         {"source": "unknown",         "confidence": 0.0,  "method": None,    "enriched_at": None},
        "cuisine_tags":        {"source": "unknown",         "confidence": 0.0,  "method": None,    "enriched_at": None},
        "course_tags":         {"source": "unknown",         "confidence": 0.0,  "method": None,    "enriched_at": None},
        "dietary_flags":       {"source": "unknown",         "confidence": 0.0,  "method": None,    "enriched_at": None},
        "flavor_tags":         {"source": "unknown",         "confidence": 0.0,  "method": None,    "enriched_at": None},
        "nutrition_per_serving":{"source": "unknown",        "confidence": 0.0,  "method": None,    "enriched_at": None},
    }
    # If the record already has cuisine data, bump its confidence
    cuisine = data.get("cuisine_tags", [])
    if _non_empty_array(cuisine):
        stub["cuisine_tags"]["source"] = "recipenlg_raw"
        stub["cuisine_tags"]["confidence"] = 0.3  # low: source is noisy
        stub["cuisine_tags"]["enriched_at"] = now

    return stub


# ---------------------------------------------------------------------------
# Main batch loop
# ---------------------------------------------------------------------------

def run(batch_size: int = 500, dry_run: bool = False, limit: int | None = None) -> None:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        log.error("Set SUPABASE_URL and SUPABASE_SERVICE_KEY env vars.")
        sys.exit(1)

    sb: Client = create_client(url, key)
    now = datetime.now(timezone.utc).isoformat()

    total_processed = 0
    total_updated = {0: 0, 1: 0, 2: 0, 3: 0}
    cursor: str | None = None  # last seen recipe_id for keyset pagination

    log.info("Starting tier profiling | batch=%d dry_run=%s limit=%s",
             batch_size, dry_run, limit)

    while True:
        query = (
            sb.table("recipes_open")
            .select(
                "recipe_id, data, enrichment_status, enrichment_flags, "
                "provenance, ingredient_count, step_count, tier"
            )
            .order("recipe_id")
            .limit(batch_size)
        )
        if cursor:
            query = query.gt("recipe_id", cursor)

        response = query.execute()
        rows = response.data or []

        if not rows:
            break

        cursor = rows[-1]["recipe_id"]
        updates = []

        for row in rows:
            new_tier, flags, new_status, prov_stub = assign_tier(row)
            old_tier = row.get("tier", 0)
            old_flags = row.get("enrichment_flags") or {}
            old_prov = row.get("provenance") or {}

            # Detect any change — include provenance seeding as a change
            tier_changed = new_tier != old_tier
            flags_changed = flags != old_flags
            prov_changed = prov_stub is not None and prov_stub != old_prov

            if tier_changed or flags_changed or prov_changed:
                upd: dict = {
                    "recipe_id": row["recipe_id"],
                    "tier": new_tier,
                    "tier_assigned_at": now,
                    "enrichment_flags": flags,
                    "enrichment_status": new_status,
                }
                if prov_changed:
                    upd["provenance"] = prov_stub
                updates.append(upd)

            total_updated[new_tier] = total_updated.get(new_tier, 0) + 1

        total_processed += len(rows)

        if updates and not dry_run:
            for upd in updates:
                patch = {k: v for k, v in upd.items() if k != "recipe_id"}
                sb.table("recipes_open").update(patch).eq(
                    "recipe_id", upd["recipe_id"]
                ).execute()

        log.info("Processed %d | this batch: %d | pending writes: %d",
                 total_processed, len(rows), len(updates))

        if limit and total_processed >= limit:
            log.info("Reached limit=%d, stopping.", limit)
            break

    log.info(
        "Done. Total=%d | Tier0=%d Tier1=%d Tier2=%d Tier3=%d | dry_run=%s",
        total_processed,
        total_updated.get(0, 0), total_updated.get(1, 0),
        total_updated.get(2, 0), total_updated.get(3, 0),
        dry_run,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tier-profile recipes_open")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute tiers but don't write to DB")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stop after N records (for testing)")
    args = parser.parse_args()
    run(batch_size=args.batch_size, dry_run=args.dry_run, limit=args.limit)
