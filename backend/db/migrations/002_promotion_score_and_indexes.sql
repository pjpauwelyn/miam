-- ============================================================
-- Migration 002: promotion_score_and_indexes
-- Target table: public.recipes_open
-- Idempotent: all statements use IF NOT EXISTS / DO NOTHING
-- Run after: 001_add_provenance_and_tiering.sql
-- Run with:  psql $DATABASE_URL -f 002_promotion_score_and_indexes.sql
--         or: Supabase MCP apply_migration
-- ============================================================

-- 1. promotion_score: deterministic 0-100 score for ranking within a tier.
--    Formula:
--      +30  real description present (has_real_description flag)
--      +20  cuisine_tags non-empty
--      +20  course_tags non-empty       ← Tier-1 criterion added 2026-04-12
--      +15  dietary_flags enriched
--      +10  flavor_tags non-empty
--      +5   nutrition_per_serving present
--    Range: 0 (nothing filled) to 100 (all criteria met).
--    Used by RAG ranking and enrichment prioritisation queues.
ALTER TABLE public.recipes_open
  ADD COLUMN IF NOT EXISTS promotion_score INTEGER
  GENERATED ALWAYS AS (
    (
      CASE WHEN (enrichment_flags->>'has_real_description')::boolean  THEN 30 ELSE 0 END
    + CASE WHEN (enrichment_flags->>'has_cuisine_tag')::boolean        THEN 20 ELSE 0 END
    + CASE WHEN (enrichment_flags->>'has_course_tag')::boolean         THEN 20 ELSE 0 END
    + CASE WHEN (enrichment_flags->>'has_dietary_flags')::boolean      THEN 15 ELSE 0 END
    + CASE WHEN (enrichment_flags->>'has_llm_flavor_tags')::boolean    THEN 10 ELSE 0 END
    + CASE WHEN (enrichment_flags->>'has_nutrition')::boolean          THEN  5 ELSE 0 END
    )
  ) STORED;

COMMENT ON COLUMN public.recipes_open.promotion_score IS
  'Deterministic 0-100 readiness score. 30=description,20=cuisine,20=course,15=diet,10=flavor,5=nutrition.';

-- 2. Index: Tier-1 embedding fetch hot path
--    Used by repair_embeddings_v2.py: WHERE tier = 1 AND (enrichment_flags->>'has_embedding')::boolean = false
CREATE INDEX IF NOT EXISTS idx_recipes_open_tier1_no_embedding
  ON public.recipes_open (recipe_id)
  WHERE tier = 1
    AND (enrichment_flags->>'has_embedding')::boolean IS NOT TRUE;

-- 3. Index: course_tags enrichment queue
--    Used by the course-tag enrichment stage to find records that need course classification.
CREATE INDEX IF NOT EXISTS idx_recipes_open_no_course_tag
  ON public.recipes_open (recipe_id, enrichment_status)
  WHERE (enrichment_flags->>'has_course_tag')::boolean IS NOT TRUE
    AND enrichment_status NOT IN ('rejected');

-- 4. Index: promotion_score within tier (for ranked retrieval)
CREATE INDEX IF NOT EXISTS idx_recipes_open_tier_score
  ON public.recipes_open (tier, promotion_score DESC)
  WHERE tier > 0;

-- 5. Index: provenance seeding queue — records that still have empty provenance
CREATE INDEX IF NOT EXISTS idx_recipes_open_no_provenance
  ON public.recipes_open (recipe_id)
  WHERE provenance = '{}'::jsonb;

-- 6. Composite: LLM enrichment queue (records at deterministic stage, not yet LLM-enriched)
CREATE INDEX IF NOT EXISTS idx_recipes_open_llm_queue
  ON public.recipes_open (recipe_id)
  WHERE enrichment_status = 'deterministic_enriched'
    AND tier < 1;
