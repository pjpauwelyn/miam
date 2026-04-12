# Handoff Note — Schema Architect Agent

**Date:** 2026-04-12
**Agent role:** Data Architect — provenance schema + tiering
**Next agent:** Data Profiler / Tiering Agent

---

## 1. What was changed and why

### `backend/models/recipe.py` — full rewrite

- Added `EnrichmentSource` enum and `FieldProvenance` model: every enrichable field group now has a typed provenance companion (`source`, `confidence`, `method`, `enriched_at`).
- Added `EnrichmentStatus` enum (raw → parsed → deterministic_enriched → llm_enriched → validated → rejected).
- Added `TierLevel` enum (0–3).
- Added `RecipeEnrichmentMeta` block with all CAT-E pipeline flags.
- `RecipeDocument` now separates fields into CAT-A (source-preserved), CAT-B (deterministic), CAT-C (externally-grounded), CAT-D (LLM-inferred), CAT-E (pipeline meta).
- All required fields that can be unknown are now `Optional` with `None` default instead of `...` — this prevents fabrication at ingest time.
- Legacy `data_quality_score` and `source_type` are now computed properties for backward compat.
- Added `tier1_eligible()` method that mirrors the DB-side criteria.

**Why:** The old model had fabrication risk (e.g. `description` was required, which forced enrichment scripts to invent stub text). The new model is honest about what is and isn't known.

### `backend/scripts/tier_profile.py` — new script

- Cursor-based, batch-restartable profiler over `recipes_open`.
- Assigns tier (0–3) and writes `enrichment_flags` based on deterministic criteria.
- Idempotent: only writes rows that changed.
- Dry-run mode: `--dry-run` for safe inspection.
- Run: `python tier_profile.py --dry-run --limit 1000` to preview.

### `backend/db/migrations/001_add_provenance_and_tiering.sql` — new migration

Adds to `recipes_open`:
- `enrichment_status` TEXT with CHECK constraint
- `tier` INTEGER (0–3) with CHECK constraint
- `tier_assigned_at` TIMESTAMPTZ
- `provenance` JSONB
- `enrichment_flags` JSONB
- `title_normalized` TEXT GENERATED (dedup/slug)
- `ingredient_count` INTEGER GENERATED
- `step_count` INTEGER GENERATED
- `promotion_blocked_reason` TEXT
- Four indexes (enrichment_status, tier, tier+status composite, partial index on raw+untiered)

**Apply it:**
```bash
psql $DATABASE_URL -f backend/db/migrations/001_add_provenance_and_tiering.sql
```
Or paste the SQL into Supabase SQL Editor. Fully idempotent via `IF NOT EXISTS`.

### `docs/SCHEMA_CONTRACT.md` — new authoritative document

Defines field categories, Tier-1 criteria table, per-stage pipeline contract, DB column map, before/after record comparison, and what RAG retrieval may assert.

---

## 2. What is now authoritative in the database

At the time of this handoff, the **Supabase migration has not yet been applied** due to a transient API error. The SQL file is at `backend/db/migrations/001_add_provenance_and_tiering.sql` and is ready to run.

Once applied, the authoritative columns on `recipes_open` will be:
- `tier` (typed integer, replaces `source_tier` for pipeline decisions)
- `enrichment_status` (stage gate)
- `enrichment_flags` (completion flags)
- `provenance` (field-level source/confidence)
- `ingredient_count` / `step_count` (generated, always fresh)
- `title_normalized` (generated, always fresh)

The existing `data` JSONB column remains the primary content store.

---

## 3. What remains unresolved

| Item | Priority | Notes |
|---|---|---|
| **Apply DB migration** | P0 | Paste SQL from `001_add_provenance_and_tiering.sql` into Supabase SQL Editor |
| **Run tier_profile.py** | P0 | After migration; use `--dry-run` first |
| **Extend enrich_recipes_fast.py** | P1 | Write provenance block + confidence back per field |
| **Nutrition enrichment script** | P1 | USDA FDC API; see gap list in SCHEMA_CONTRACT.md |
| **Dedup script** | P2 | `title_normalized` column is ready; script not written |
| **Tier-1 filter on embeddings** | P1 | `repair_embeddings_v2.py` must filter `WHERE tier = 1` |
| **Description stub classifier** | P2 | Improve beyond simple startswith heuristic |

---

## 4. What the next agent should consume

- **Read:** `docs/SCHEMA_CONTRACT.md` — the canonical field contract.
- **Read:** `backend/models/recipe.py` — `RecipeDocument`, `TierLevel`, `EnrichmentStatus`, `FieldProvenance`.
- **Run first:** Apply migration, then `python backend/scripts/tier_profile.py --dry-run --limit 5000` to get a tier distribution snapshot.
- **Query:** `SELECT tier, COUNT(*) FROM recipes_open GROUP BY tier ORDER BY tier;` after profiling to understand the starting tier distribution.

---

## 5. What should NOT be touched

| Item | Reason |
|---|---|
| `data->>'title'` in any record | CAT-A, immutable post-ingest |
| `raw_ingredients_text` | Source-preserved, used for re-parsing |
| `nutrition_per_serving` in data | Only USDA/OFF scripts may write this |
| `source_tier` column | Legacy — leave in place but ignore for pipeline logic |
| `embeddings_open` table | Do not re-embed until Tier-1 filter is in place |
| Any record with `promotion_blocked_reason` set | Human/system override, respect it |

---

## 6. Remaining risks

| Risk | Severity | Mitigation |
|---|---|---|
| Migration not applied | HIGH | SQL file is ready; apply via Supabase SQL Editor |
| Existing enriched records all have `enrichment_status = 'raw'` after migration | MEDIUM | Run `UPDATE recipes_open SET enrichment_status = 'deterministic_enriched' WHERE data->>'source_type' = 'recipenlg_enriched';` after migration |
| `dietary_flags` all-False may be misread as unenriched | MEDIUM | tier_profile.py checks this; enrichment scripts should set a `has_dietary_flags` flag explicitly |
| Stub descriptions ("A recipe for...") will block Tier-1 even on otherwise good records | MEDIUM | Expected — these records need LLM re-enrichment for description |
| 1.15M records: tier_profile.py will take ~30 min at batch=500 | LOW | Use `--batch-size 2000`; script is restartable |
| Supabase free-tier row count limits on `recipes_open` | LOW | Monitor; if needed, partition or archive Tier-3 records |
