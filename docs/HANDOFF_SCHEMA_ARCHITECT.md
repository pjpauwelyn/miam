# Handoff Note — Data Architect Agent

**Agent role:** Data Architect (schema + enrichment pipeline)
**Handoff date:** 2026-04-12
**Next agent:** Profiling / Tiering Agent
**Repo:** `pjpauwelyn/miam`
**Relevant branches:** `main` (all changes on main; no feature branch)

---

## 1. What Was Changed and Why

### `backend/models/recipe.py`

**What:** Added two fields to `RecipeEnrichmentMeta`:
- `has_course_tag: bool = False` — was missing despite being a hard Tier-1 criterion
  in both `tier1_eligible()` and the contract. Without it, the flags block couldn't
  be used to answer "why is this recipe not Tier 1?" for course-tag failures.
- `rag_embedding_version: Optional[str] = None` — tracks which embedding model
  produced the current vector. Without this, there is no way to detect stale
  embeddings after a model upgrade without re-querying the embeddings table.

Also added `rag_embedding_version` to the content `RecipeDocument` itself (alongside
`embedding_text`) so it round-trips correctly through the JSONB data column.

**Why now:** Both gaps were silent — no runtime errors, but they created invisible
blind spots in the pipeline dashboard and made Tier-1 promotion logic fragile.

### `backend/scripts/tier_profile.py`

**What:**
1. `_build_flags()` now includes `has_course_tag` — preserves the embedding flags
   (`has_embedding`, `rag_embedding_version`) from the existing record instead of
   zeroing them on re-run.
2. `assign_tier()` now returns a 4-tuple including `provenance_stub_or_none`.
3. `_maybe_seed_provenance()` new helper — writes a minimal provenance skeleton
   (`{title, description, cuisine_tags, course_tags, dietary_flags, flavor_tags,
   nutrition_per_serving}` all as `{source: unknown, confidence: 0.0}`) when a
   record has `provenance = {}`. This means the provenance column is never an
   empty object after the first profiling pass, making SQL observability queries
   reliable (e.g. `WHERE provenance->>'description' IS NOT NULL`).
4. `course_tags non-empty` added as explicit Tier-1 gate in `assign_tier()`.
5. Batch write loop updated to: (a) select `provenance` in the read query,
   (b) include `provenance` in the update payload when a stub was seeded,
   (c) extract `patch` dict cleanly from the update dict.

**Why now:** `has_course_tag` was the only Tier-1 criterion with no flag, making it
impossible to use `enrichment_flags` to explain why a recipe isn't Tier 1. The
provenance seeding makes the column useful for downstream queries immediately.

### `backend/db/migrations/002_promotion_score_and_indexes.sql`

**What:** New migration (idempotent) adding:
- `promotion_score` — deterministic generated INT column (0–100) computed from
  `enrichment_flags`. Weights: description=30, cuisine=20, course=20, dietary=15,
  flavor=10, nutrition=5.
- `idx_recipes_open_tier1_no_embedding` — hot path for `repair_embeddings_v2.py`.
- `idx_recipes_open_no_course_tag` — enrichment queue for the course-tag pass.
- `idx_recipes_open_tier_score` — ranked retrieval within a tier.
- `idx_recipes_open_no_provenance` — provenance seeding queue.
- `idx_recipes_open_llm_queue` — LLM enrichment queue.

**Why now:** Without `promotion_score`, ranking within Tier 1 requires runtime JSON
traversal across 1.2M rows. The generated column makes it a single index scan.

### `docs/SCHEMA_CONTRACT.md`

**What:** Bumped to v2.1. Changes:
- Added `has_course_tag` to the Tier-1 criteria table and the flags schema table.
- Added `rag_embedding_version` to the flags table.
- Added `promotion_score` to the DB column map.
- Updated the before/after sample records to include `has_course_tag` and
  `rag_embedding_version` in the flags block.
- Rewrote the Remaining Gaps section with a concrete owner/blocker per item.

---

## 2. What Is Now Authoritative in the Database

After running `tier_profile.py` (which is idempotent and safe to run immediately):

- `tier` — set for all records (0–3).
- `enrichment_flags` — complete set of 10 flags including `has_course_tag`.
- `provenance` — seeded with skeleton stubs for records that previously had `{}`.
- `enrichment_status` — promoted to `validated` for any record that passes Tier-1.
- `tier_assigned_at` — updated timestamp.

After applying migration 002:
- `promotion_score` — live generated column, always current.
- All six new indexes — available for query planner.

---

## 3. What Remains Unresolved

| Issue | Priority | Notes |
|---|---|---|
| ~90%+ of records have `has_course_tag = false` | CRITICAL | Tier-1 gated on this; need a course-tag rule enrichment pass before LLM stage |
| `enrich_recipes_fast.py` does not write `provenance->description->confidence` | HIGH | LLM-inferred descriptions silently fail the confidence check in `tier1_eligible()` |
| No `enrich_nutrition_usda.py` | MEDIUM | Nutrition stays null; RAG must handle gracefully |
| `repair_embeddings_v2.py` embeds all records, not just Tier-1 | MEDIUM | Wastes embedding budget; add `WHERE tier = 1` |
| `repair_embeddings_v2.py` does not write `rag_embedding_version` | MEDIUM | Stale-embedding detection is blind until this is added |
| Deduplication not implemented | LOW | `title_normalized` + `idx` ready; script not written |
| `_is_stub_description()` heuristic is minimal | LOW | 4 patterns; expand to regex classifier |

---

## 4. What the Next Agent Should Consume

The **Profiling / Tiering Agent** should:

1. **Run `tier_profile.py --dry-run --limit 1000`** to validate the new flags
   and provenance seeding logic before a full pass.
2. **Run `tier_profile.py` (full pass)** to propagate `has_course_tag` and seed
   provenance stubs across all 1.2M records.
3. **Query the tier distribution** to establish a baseline:
   ```sql
   SELECT tier, COUNT(*) FROM recipes_open GROUP BY tier ORDER BY tier;
   ```
4. **Identify the dominant Tier-1 blocker** by running:
   ```sql
   SELECT
     (enrichment_flags->>'has_course_tag')::boolean   AS course_tag,
     (enrichment_flags->>'has_cuisine_tag')::boolean  AS cuisine_tag,
     (enrichment_flags->>'has_real_description')::boolean AS description,
     COUNT(*)
   FROM recipes_open
   WHERE tier = 2
   GROUP BY 1, 2, 3
   ORDER BY count DESC
   LIMIT 20;
   ```
5. **Apply migration 002** via `supabase db push` or Supabase MCP `apply_migration`
   with `name = '002_promotion_score_and_indexes'`.
6. **Report back:** how many records are at each tier, and which single flag is
   blocking the most Tier-2 records from Tier-1 promotion.

---

## 5. What Should NOT Be Touched

| Resource | Reason |
|---|---|
| `recipes_open.data` JSONB | `tier_profile.py` must never modify content fields |
| `raw_ingredients_text` inside `data` | Immutable CAT-A source |
| `enrichment_flags.has_embedding` | Only `repair_embeddings_v2.py` owns this |
| `enrichment_flags.rag_embedding_version` | Only `repair_embeddings_v2.py` owns this |
| `provenance` keys that are already non-null | The seeding stub is write-once for empty records |
| `source_tier` column | Legacy, not used in pipeline decisions |
| `nutrition_per_serving` in `data` | Only `enrich_nutrition_usda.py` (future) may write this |
| Migration 001 SQL | Already applied; do not re-run or modify |

---

## 6. Remaining Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `has_course_tag` blocks nearly all Tier-1 promotion | HIGH | HIGH | Run course-tag rule enrichment pass before expecting any Tier-1 records |
| LLM descriptions silently fail confidence check | HIGH | MEDIUM | `enrich_recipes_fast.py` must write confidence; add to that script's next PR |
| `promotion_score` CASE expression references `enrichment_flags` as JSONB — if a record has `enrichment_flags = null` rather than `'{}'`, the generated col will produce 0, not an error | LOW | LOW | Migration 001 sets `DEFAULT '{}'` NOT NULL; existing rows should be safe, but verify with `SELECT COUNT(*) FROM recipes_open WHERE enrichment_flags IS NULL` |
| Provenance seeding overwrites a legitimately empty `{}` provenance | VERY LOW | LOW | `_maybe_seed_provenance` returns None if `existing` is truthy; first write is a seed, subsequent writes by enrichment scripts overwrite individual keys |
| `tier_profile.py` update loop uses per-row UPDATE, not batch upsert | MEDIUM | MEDIUM | For 1.2M rows this is slow (~20 min); acceptable for now, but should be batched with `upsert()` in a future performance pass |
