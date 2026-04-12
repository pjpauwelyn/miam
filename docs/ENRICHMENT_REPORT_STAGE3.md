# MIAM Stage 3 — Deterministic Enrichment Report

**Version:** 1.0  
**Schema Contract:** v2.1  
**Stage:** 3 — Deterministic Enrichment (course_tags + dietary_flags)  
**Prepared by:** Deterministic Enrichment Agent  
**Date:** 2026-04-12  
**Status:** ⏳ Pending execution (Supabase MCP unavailable at authoring time — fill in after running)

---

## Summary

This report captures the output of the Stage 3 pipeline after running:
1. `migration 001_add_provenance_and_tiering`
2. `migration 002_promotion_score_and_indexes`
3. `enrich_course_tags.py --batch-size 1000`
4. `enrich_dietary_flags.py --batch-size 1000`
5. `tier_profile.py --batch-size 1000`

**Key claim:** After Stage 3, every recipe with non-empty ingredients + steps is
one LLM-generated description away from reaching Tier 1. Stage 4 only needs to
replace stub descriptions.

---

## Tier Distribution

> Run after `tier_profile.py` completes:
>
> ```sql
> SELECT tier,
>        COUNT(*),
>        ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 2) AS pct
> FROM recipes_open
> GROUP BY tier
> ORDER BY tier;
> ```

| tier | count | pct |
|------|-------|-----|
| 0    | TBD   | TBD |
| 1    | TBD (~0 expected — blocked by stub descriptions) | TBD |
| 2    | TBD (~94% expected) | TBD |
| 3    | TBD (~5% expected)  | TBD |

---

## Enrichment Flag Coverage

> Run after `tier_profile.py` completes:
>
> ```sql
> SELECT
>   COUNT(*) FILTER (WHERE (enrichment_flags->>'has_course_tag')::bool)    AS has_course,
>   COUNT(*) FILTER (WHERE (enrichment_flags->>'has_dietary_flags')::bool)  AS has_dietary,
>   COUNT(*) FILTER (WHERE enrichment_status = 'deterministic_enriched')   AS det_enriched,
>   COUNT(*) AS total
> FROM recipes_open;
> ```

| metric | count | pct of total |
|--------|-------|--------------|
| has_course_tag = true | TBD | TBD (target: ≥70%) |
| has_dietary_flags = true | TBD | TBD (target: ≥80%) |
| enrichment_status = deterministic_enriched | TBD | TBD |
| total rows | 1,150,214 (recipes_open) | 100% |

---

## Records One Description Away from Tier 1

> ```sql
> SELECT COUNT(*)
> FROM recipes_open
> WHERE enrichment_status = 'deterministic_enriched'
>   AND (enrichment_flags->>'has_course_tag')::bool = true
>   AND (enrichment_flags->>'has_dietary_flags')::bool = true
>   AND ingredient_count >= 2
>   AND step_count >= 2
>   AND length(data->>'title') >= 5;
> ```

| metric | count |
|--------|-------|
| Tier-1 candidates (need only description) | TBD |
| % of total corpus | TBD |

---

## Stage 4 LLM Handoff Queue

Stage 4 should query in this priority order:

```sql
SELECT recipe_id, data->>'title' AS title, promotion_score, ingredient_count
FROM recipes_open
WHERE enrichment_status = 'deterministic_enriched'
  AND (enrichment_flags->>'has_course_tag')::bool = true
ORDER BY promotion_score DESC, ingredient_count DESC
LIMIT 100;
```

Highest `promotion_score` records should be enriched first to maximise
Tier-1 count per API dollar spent.

After LLM writes `data->description`:
1. Set `enrichment_status = 'llm_enriched'`
2. Re-run `tier_profile.py` — Tier-1 count materialises here

---

## Script Inventory

| Script | Status | Output column | enrichment_status set |
|--------|--------|---------------|-----------------------|
| `tier_profile.py` | ✅ Fixed (Fix1+Fix2) | CAT-E only | validates existing status |
| `enrich_course_tags.py` | ✅ Committed | data->course_tags | course_tagged |
| `enrich_dietary_flags.py` | ✅ Committed | data->dietary_flags | dietary_tagged → deterministic_enriched |

---

## Known Remaining Gaps (for Stage 4 + beyond)

| Gap | Impact on Tier 1 | Owner |
|-----|-----------------|-------|
| Stub descriptions (~100% of corpus) | **HARD BLOCKER** | Stage 4 LLM |
| cuisine_tags ~75-85% ["Other"] | Not a blocker (non-empty ✓) | Stage 7 optional |
| Fraction parser bug (⅓→13) | Not a blocker | Stage 8 optional |
| Nutrition data | Not a blocker (Stage 5) | enrich_nutrition_usda.py |

---

## Execution Runbook

If Supabase MCP is available, run these steps in order:

### Step 1 — Apply migrations

```bash
# Via Supabase MCP (preferred)
supabase db push  # or apply via MCP tool

# Via psql directly
psql $DATABASE_URL -f backend/db/migrations/001_add_provenance_and_tiering.sql
psql $DATABASE_URL -f backend/db/migrations/002_promotion_score_and_indexes.sql
```

Verify after 001:
```sql
SELECT COUNT(*) FROM recipes_open WHERE enrichment_status = 'raw' AND tier = 0;
-- Expected: 1,150,214
```

Verify after 002:
```sql
SELECT COUNT(*) FROM recipes_open WHERE promotion_score = 0;
-- Expected: ~1,150,214 (enrichment_flags all empty at this point)
```

### Step 2 — Validate tier_profile.py

```bash
cd backend/scripts
python tier_profile.py --dry-run --limit 100
# Expected: ~0 Tier1, ~94 Tier2, ~5 Tier3, ~1 Tier0
```

Confirm both fixes are present:
- Fix 1: `_has_dietary_flags(data)` in the Tier-1 boolean (✅ present)
- Fix 2: `sb.table("recipes_open").upsert(updates).execute()` (✅ fixed 2026-04-12)

### Step 3 — Run course tag classifier

```bash
python enrich_course_tags.py --batch-size 1000
# Logs every 10k rows. Full corpus ~1.15M rows.
# Expected coverage: >=70% non-'other' tags
```

### Step 4 — Run dietary flag classifier

```bash
python enrich_dietary_flags.py --batch-size 1000
# Logs every 10k rows.
# Expected: ~80%+ records get at least one True flag
```

### Step 5 — Re-run tier profiler

```bash
python tier_profile.py --batch-size 1000
# Full corpus pass. Updates tier, enrichment_flags, provenance.
```

### Step 6 — Run validation queries (fill in table above)

```sql
-- Tier distribution
SELECT tier, COUNT(*), ROUND(100.0*COUNT(*)/SUM(COUNT(*)) OVER(), 2) AS pct
FROM recipes_open GROUP BY tier ORDER BY tier;

-- Flag coverage
SELECT
  COUNT(*) FILTER (WHERE (enrichment_flags->>'has_course_tag')::bool) AS has_course,
  COUNT(*) FILTER (WHERE (enrichment_flags->>'has_dietary_flags')::bool) AS has_dietary,
  COUNT(*) FILTER (WHERE enrichment_status = 'deterministic_enriched') AS det_enriched,
  COUNT(*) AS total
FROM recipes_open;
```
