-- ==========================================================================
-- MIAM — 100k Stratified Selection from recipes_open
-- ==========================================================================
--
-- Replaces slim_to_100k.py (client-side, 2.8 GB transfer) with a
-- server-side SQL approach that never moves data off the database.
--
-- Run in Supabase SQL Editor or as a migration.
-- Estimated execution: 2–5 minutes on 1.15M rows.
--
-- IMPORTANT: Run each step separately in the SQL Editor.
-- The SQL Editor has a ~60s timeout per statement, so the DELETE
-- must be chunked (Step 4 is a loop).
-- ==========================================================================


-- =========================================================================
-- STEP 1: Add working column
-- =========================================================================

ALTER TABLE recipes_open ADD COLUMN IF NOT EXISTS _keep BOOLEAN DEFAULT FALSE;


-- =========================================================================
-- STEP 2: Score, stratify, and flag survivors in one pass
-- =========================================================================

WITH scored AS (
  SELECT
    recipe_id,

    -- ── Quality score (0–100) ──────────────────────────────────────────

    -- Ingredient count sweet spot: 5–15 = 25pts, 3–20 = 15pts, ≥2 = 5pts
    CASE
      WHEN jsonb_array_length(COALESCE(data->'ingredients', '[]'::jsonb)) BETWEEN 5 AND 15 THEN 25
      WHEN jsonb_array_length(COALESCE(data->'ingredients', '[]'::jsonb)) BETWEEN 3 AND 20 THEN 15
      WHEN jsonb_array_length(COALESCE(data->'ingredients', '[]'::jsonb)) >= 2 THEN 5
      ELSE 0
    END
    +
    -- Step count sweet spot: 4–12 = 25pts, 2–15 = 15pts, ≥1 = 5pts
    CASE
      WHEN jsonb_array_length(COALESCE(data->'steps', data->'directions', '[]'::jsonb)) BETWEEN 4 AND 12 THEN 25
      WHEN jsonb_array_length(COALESCE(data->'steps', data->'directions', '[]'::jsonb)) BETWEEN 2 AND 15 THEN 15
      WHEN jsonb_array_length(COALESCE(data->'steps', data->'directions', '[]'::jsonb)) >= 1 THEN 5
      ELSE 0
    END
    +
    -- Title length: 10–60 chars = 20pts, 5–80 = 10pts
    CASE
      WHEN length(TRIM(COALESCE(data->>'title', ''))) BETWEEN 10 AND 60 THEN 20
      WHEN length(TRIM(COALESCE(data->>'title', ''))) BETWEEN 5 AND 80 THEN 10
      ELSE 0
    END
    +
    -- Cuisine tag present and not generic: 20pts; generic: 5pts
    CASE
      WHEN COALESCE(data->'cuisine_tags'->>0, '') NOT IN ('', 'Other', 'Unknown', 'other')
           AND data->'cuisine_tags'->>0 IS NOT NULL THEN 20
      WHEN data->'cuisine_tags'->>0 IS NOT NULL THEN 5
      ELSE 0
    END
    +
    -- NER present: 10pts
    CASE
      WHEN jsonb_array_length(COALESCE(data->'NER', '[]'::jsonb)) > 0 THEN 10
      ELSE 0
    END
    AS quality_score,

    -- ── Stratum key: cuisine::course ─────────────────────────────────
    COALESCE(
      NULLIF(NULLIF(NULLIF(data->'cuisine_tags'->>0, 'Other'), 'Unknown'), ''),
      'Unknown'
    )
    || '::'
    || COALESCE(NULLIF(data->'course_tags'->>0, ''), 'unknown')
    AS stratum

  FROM recipes_open
  WHERE length(TRIM(COALESCE(data->>'title', ''))) >= 5  -- drop stub titles
),

-- Count per stratum, compute proportional allocation
stratum_sizes AS (
  SELECT stratum, COUNT(*) AS cnt
  FROM scored
  WHERE quality_score >= 10  -- minimum quality gate
  GROUP BY stratum
),
total_eligible AS (
  SELECT SUM(cnt) AS total FROM stratum_sizes
),
allocation AS (
  SELECT
    s.stratum,
    s.cnt,
    CASE
      -- Small strata: keep everything (protected minority)
      WHEN s.cnt <= 50 THEN s.cnt
      -- Large strata: proportional share with floor of 50
      ELSE GREATEST(50, LEAST(s.cnt,
        FLOOR(100000.0 * s.cnt / GREATEST(t.total, 1))::int
      ))
    END AS seats
  FROM stratum_sizes s
  CROSS JOIN total_eligible t
),

-- Rank within stratum, pick top-N
ranked AS (
  SELECT
    sc.recipe_id,
    sc.stratum,
    sc.quality_score,
    ROW_NUMBER() OVER (
      PARTITION BY sc.stratum
      ORDER BY sc.quality_score DESC, sc.recipe_id  -- deterministic tiebreak
    ) AS rn
  FROM scored sc
  WHERE sc.quality_score >= 10
)

-- Flag survivors
UPDATE recipes_open ro
SET _keep = TRUE
FROM ranked r
JOIN allocation a ON r.stratum = a.stratum
WHERE ro.recipe_id = r.recipe_id
  AND r.rn <= a.seats;


-- =========================================================================
-- STEP 3: Verify counts before deletion
-- =========================================================================

-- Run this to check the selection looks right:
SELECT
  COUNT(*) FILTER (WHERE _keep = TRUE)  AS kept,
  COUNT(*) FILTER (WHERE _keep IS NOT TRUE) AS to_delete,
  COUNT(*) AS total
FROM recipes_open;

-- Also check stratum distribution:
SELECT
  COALESCE(
    NULLIF(NULLIF(NULLIF(data->'cuisine_tags'->>0, 'Other'), 'Unknown'), ''),
    'Unknown'
  ) AS cuisine,
  COUNT(*) AS cnt
FROM recipes_open
WHERE _keep = TRUE
GROUP BY 1
ORDER BY 2 DESC
LIMIT 30;


-- =========================================================================
-- STEP 4: Chunked deletion (run repeatedly until 0 rows affected)
-- =========================================================================

-- Run this statement repeatedly until it reports "0 rows affected".
-- Each execution deletes up to 50,000 non-surviving rows.
-- Estimated iterations: ~21 for 1.05M deletions.

DELETE FROM recipes_open
WHERE recipe_id IN (
  SELECT recipe_id FROM recipes_open
  WHERE _keep IS NOT TRUE
  LIMIT 50000
);

-- After completion, check remaining count:
-- SELECT COUNT(*) FROM recipes_open;


-- =========================================================================
-- STEP 5: Cleanup
-- =========================================================================

-- Drop the working column
ALTER TABLE recipes_open DROP COLUMN IF EXISTS _keep;

-- Reclaim disk space (may take a few minutes)
-- NOTE: VACUUM FULL requires exclusive lock. Run during low-traffic window.
-- Expected post-vacuum size: ~225 MB table + ~120 MB index (from ~2.6 GB)
VACUUM FULL recipes_open;

-- Rebuild indexes for optimal query performance
REINDEX TABLE recipes_open;


-- =========================================================================
-- STEP 6: Add enrichment tracking columns
-- =========================================================================

-- These columns track pipeline progress without polluting the JSONB data column.

ALTER TABLE recipes_open
  ADD COLUMN IF NOT EXISTS enrichment_status TEXT DEFAULT 'raw',
  ADD COLUMN IF NOT EXISTS enrichment_confidence REAL,
  ADD COLUMN IF NOT EXISTS enrichment_flags JSONB DEFAULT '{}'::jsonb;

-- Create index for pipeline queries
CREATE INDEX IF NOT EXISTS idx_recipes_open_enrichment_status
  ON recipes_open (enrichment_status);

-- Verify final state
SELECT COUNT(*) AS final_count FROM recipes_open;
