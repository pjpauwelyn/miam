-- ============================================================
-- Migration 001: add_provenance_and_tiering
-- Target table: public.recipes_open
-- Idempotent: all statements use IF NOT EXISTS / DO NOTHING
-- Run with: psql $DATABASE_URL -f 001_add_provenance_and_tiering.sql
--        or: Supabase MCP apply_migration
-- ============================================================

-- 1. enrichment_status: pipeline stage gate
ALTER TABLE public.recipes_open
  ADD COLUMN IF NOT EXISTS enrichment_status TEXT NOT NULL DEFAULT 'raw'
  CHECK (enrichment_status IN (
    'raw', 'parsed', 'deterministic_enriched',
    'llm_enriched', 'validated', 'rejected'
  ));

-- 2. tier: quality tier (0=untiered, 1=Tier1/RAG-ready, 2=Tier2, 3=Tier3)
ALTER TABLE public.recipes_open
  ADD COLUMN IF NOT EXISTS tier INTEGER NOT NULL DEFAULT 0
  CHECK (tier BETWEEN 0 AND 3);

-- 3. tier_assigned_at: when tier was last computed
ALTER TABLE public.recipes_open
  ADD COLUMN IF NOT EXISTS tier_assigned_at TIMESTAMPTZ;

-- 4. provenance: field-level source/confidence map
--    { "field_group": { "source": "...", "confidence": 0.0-1.0,
--                       "method": "...", "enriched_at": "ISO8601" } }
ALTER TABLE public.recipes_open
  ADD COLUMN IF NOT EXISTS provenance JSONB NOT NULL DEFAULT '{}';

-- 5. enrichment_flags: boolean completion flags per stage
--    { "has_parsed_ingredients": bool, "has_normalised_units": bool,
--      "has_dietary_flags": bool, "has_cuisine_tag": bool,
--      "has_real_description": bool, "has_llm_flavor_tags": bool,
--      "has_nutrition": bool, "has_embedding": bool }
ALTER TABLE public.recipes_open
  ADD COLUMN IF NOT EXISTS enrichment_flags JSONB NOT NULL DEFAULT '{}';

-- 6. title_normalized: cleaned title for deduplication and slug generation
ALTER TABLE public.recipes_open
  ADD COLUMN IF NOT EXISTS title_normalized TEXT
  GENERATED ALWAYS AS (
    lower(trim(regexp_replace(data->>'title', '[^a-zA-Z0-9 ]', '', 'g')))
  ) STORED;

-- 7. ingredient_count: avoids JSON traversal in WHERE clauses
ALTER TABLE public.recipes_open
  ADD COLUMN IF NOT EXISTS ingredient_count INTEGER
  GENERATED ALWAYS AS (
    jsonb_array_length(COALESCE(data->'ingredients', '[]'))
  ) STORED;

-- 8. step_count: avoids JSON traversal in WHERE clauses
ALTER TABLE public.recipes_open
  ADD COLUMN IF NOT EXISTS step_count INTEGER
  GENERATED ALWAYS AS (
    jsonb_array_length(COALESCE(data->'steps', '[]'))
  ) STORED;

-- 9. promotion_blocked_reason: human/system override
ALTER TABLE public.recipes_open
  ADD COLUMN IF NOT EXISTS promotion_blocked_reason TEXT;

-- ---- Indexes ---------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_recipes_open_enrichment_status
  ON public.recipes_open (enrichment_status);

CREATE INDEX IF NOT EXISTS idx_recipes_open_tier
  ON public.recipes_open (tier);

CREATE INDEX IF NOT EXISTS idx_recipes_open_tier_status
  ON public.recipes_open (tier, enrichment_status);

-- Hot path for enrichment scripts: unprocessed raw records
CREATE INDEX IF NOT EXISTS idx_recipes_open_raw_untiered
  ON public.recipes_open (recipe_id)
  WHERE enrichment_status = 'raw' AND tier = 0;

-- ---- Column comments -------------------------------------------------------

COMMENT ON COLUMN public.recipes_open.enrichment_status IS
  'Pipeline stage: raw > parsed > deterministic_enriched > llm_enriched > validated | rejected';
COMMENT ON COLUMN public.recipes_open.tier IS
  '0=untiered, 1=Tier1/RAG-ready, 2=Tier2/usable, 3=Tier3/skeleton';
COMMENT ON COLUMN public.recipes_open.provenance IS
  'Per-field-group provenance: {group: {source, confidence, method, enriched_at}}';
COMMENT ON COLUMN public.recipes_open.enrichment_flags IS
  'Boolean completion flags for fast pipeline progress queries';
COMMENT ON COLUMN public.recipes_open.title_normalized IS
  'Lowercase alphanumeric-only title for dedup and slug generation';
COMMENT ON COLUMN public.recipes_open.ingredient_count IS
  'Computed from data->ingredients array length; used in tier criteria';
COMMENT ON COLUMN public.recipes_open.step_count IS
  'Computed from data->steps array length; used in tier criteria';
