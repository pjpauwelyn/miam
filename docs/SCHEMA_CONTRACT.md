# MIAM Recipe Schema Contract

**Version:** 2.0 (provenance-aware)
**Effective from:** 2026-04-12
**Authoritative source:** `backend/models/recipe.py` — `RecipeDocument`

---

## Purpose

This document is the single source of truth for:

1. What fields exist and what category they belong to.
2. What each pipeline stage is responsible for filling.
3. What "Tier 1" means concretely.
4. What downstream consumers (RAG retrieval, UI, evaluation) may rely on.

---

## Field Categories

| Category | Label | Written by | Overwritable? | Example fields |
|---|---|---|---|---|
| **CAT-A** | Source-preserved | Ingest script | Never | `title`, `raw_ingredients_text`, `source_url` |
| **CAT-B** | Deterministic-derived | Rule scripts | Only by newer rule version | `ingredients` (parsed), `dietary_flags`, `course_tags`, `time_*` |
| **CAT-C** | Externally-grounded | USDA / OFF lookup | Only by newer API call | `nutrition_per_serving` |
| **CAT-D** | LLM-inferred | LLM enrichment scripts | Only with higher confidence | `description`, `cuisine_tags`, `flavor_tags`, `occasion_tags` |
| **CAT-E** | Pipeline metadata | Pipeline scripts | Always | `tier`, `enrichment_status`, `enrichment_flags`, `provenance` |

### Immutability rules

- **CAT-A fields are immutable after ingestion.** No enrichment script may overwrite them.
- **CAT-B fields may only be overwritten** if the new rule version is explicitly tagged in provenance.
- **CAT-C nutrition** must come from an external API. LLMs must never write `nutrition_per_serving`.
- **CAT-D fields** are tagged with `confidence`. A script should only overwrite an existing CAT-D field if its own confidence exceeds the stored value.
- **CAT-E fields** are always owned by the pipeline and are always fresh.

---

## Tier Definitions

### Tier 1 — RAG-Ready (the goal)

A recipe is **Tier 1** if and only if all of the following hold:

| Criterion | Threshold | Field |
|---|---|---|
| Title present | len >= 5 chars | `data->>'title'` |
| Parsed ingredients | >= 2 items | `ingredient_count` (computed column) |
| Structured steps | >= 2 steps | `step_count` (computed column) |
| Real description | >= 80 chars, not a stub phrase | `data->>'description'` |
| Cuisine classified | non-empty array | `data->'cuisine_tags'` |
| Course classified | non-empty array | `data->'course_tags'` |
| Pipeline stage | deterministic_enriched, llm_enriched, or validated | `enrichment_status` |
| Description confidence | >= 0.6 (if LLM-produced) | `provenance->description->confidence` |

Tier-1 recipes are stored with `tier = 1`. They are eligible as RAG context.

### Tier 2 — Usable, Incomplete

- Title present (len >= 3)
- `ingredient_count >= 2`
- `step_count >= 1`
- Does NOT meet Tier 1

Tier-2 recipes may be used for non-critical features (discovery browsing, suggestions). Not primary RAG context.

### Tier 3 — Skeleton

- Title present (len >= 1)
- Does NOT meet Tier 2

Skeleton records are retained in the DB but not served to the LLM. Kept for re-enrichment attempts.

### Tier 0 — Untiered / Blocked

- No usable title, OR `enrichment_status = 'rejected'`
- Explicitly suppressed via `promotion_blocked_reason`

---

## Pipeline Stage Contract

### Stage 1 — Ingest (`ingest_recipenlg_chunks.py`)

**Reads:** RecipeNLG raw CSV/parquet  
**Writes (CAT-A):** `title`, `raw_ingredients_text`, `source_url`, `source_dataset`  
**Sets:** `enrichment_status = 'raw'`, `tier = 0`  
**Must not touch:** Any other field  

### Stage 2 — Parse & Normalise (rule-based)

**Script:** extend `enrich_recipenlg.py`  
**Reads:** raw records (`enrichment_status = 'raw'`)  
**Writes (CAT-B):** `ingredients` (parsed), `steps`, `dietary_flags`, `course_tags`, `time_*`, `serves`  
**Sets:** `enrichment_status = 'parsed'`, provenance source = `rule_deterministic`  
**Must not touch:** CAT-A fields, CAT-D fields  

### Stage 3 — Deterministic Enrichment

**Script:** `enrich_db_cuisines.py` + extend with dietary-flag rules  
**Reads:** parsed records (`enrichment_status = 'parsed'`)  
**Writes (CAT-B):** `dietary_flags`, `season_tags`, title-based `course_tags` override  
**Sets:** `enrichment_status = 'deterministic_enriched'`  
**Must not touch:** CAT-A, CAT-D  

### Stage 4 — LLM Enrichment

**Script:** `enrich_recipes_fast.py`  
**Reads:** deterministic_enriched records  
**Writes (CAT-D):** `description`, `cuisine_tags`, `region_tag`, `flavor_tags`, `texture_tags`, `occasion_tags`, `difficulty`, `tips`  
**Sets:** `enrichment_status = 'llm_enriched'`, provenance source = `llm_mistral` (or other)  
**Confidence threshold:** only write if LLM-assigned confidence >= 0.6  
**Must not touch:** CAT-A, CAT-B, CAT-C  

### Stage 5 — Nutrition Grounding

**Script:** future `enrich_nutrition_usda.py`  
**Reads:** llm_enriched records  
**Writes (CAT-C):** `nutrition_per_serving`  
**Sets:** provenance source = `usda_fdc` or `open_food_facts`, confidence = 0.8–1.0  
**Rule:** If USDA match confidence < 0.5, leave `nutrition_per_serving = null`. NEVER fabricate.  

### Stage 6 — Tier Profiling

**Script:** `tier_profile.py`  
**Reads:** any record  
**Writes (CAT-E only):** `tier`, `tier_assigned_at`, `enrichment_flags`  
**Must not touch:** data JSONB, provenance content  
**Frequency:** after every enrichment stage; safe to run continuously  

### Stage 7 — Embedding

**Script:** `repair_embeddings_v2.py` (extended for Tier-1 filter)  
**Reads:** Tier-1 records (`tier = 1`)  
**Writes:** `embeddings_open` table  
**Sets:** `enrichment_flags.has_embedding = true`  
**Must not touch:** `recipes_open.data`  

---

## DB Column Map

The `recipes_open` table stores content in `data` JSONB plus these typed columns:

| Column | Type | Purpose |
|---|---|---|
| `recipe_id` | UUID PK | Stable identifier |
| `data` | JSONB | Full RecipeDocument content fields |
| `source` | TEXT | Dataset name (e.g. `recipenlg`) |
| `source_tier` | INT | Legacy — superseded by `tier` column |
| `enrichment_status` | TEXT | Stage gate |
| `tier` | INT | Quality tier (0–3) |
| `tier_assigned_at` | TIMESTAMPTZ | Last tier computation |
| `provenance` | JSONB | Per-field-group provenance map |
| `enrichment_flags` | JSONB | Boolean completion flags |
| `title_normalized` | TEXT (generated) | For dedup / slug |
| `ingredient_count` | INT (generated) | From `data->ingredients` |
| `step_count` | INT (generated) | From `data->steps` |
| `promotion_blocked_reason` | TEXT | Human/system override |
| `created_at` | TIMESTAMPTZ | Ingest timestamp |

---

## Before / After Record Comparison

### BEFORE (raw ingest state)

```json
{
  "recipe_id": "cae6dcbe-...",
  "source": "recipenlg",
  "source_tier": 1,
  "data": {
    "title": "Shrimp Scampi I.E.S.Jjgf65a",
    "description": "A recipe for Shrimp Scampi I.E.S.Jjgf65a.",
    "cuisine_tags": ["Other"],
    "flavor_tags": [],
    "dietary_tags": [],
    "data_quality_score": 0.75,
    "nutrition_per_serving": null
  }
}
```

Problems: stub description, vague cuisine, no flavor/texture tags, no dietary enrichment, no nutrition, no provenance, no tier.

### AFTER (Tier-1 state)

```json
{
  "recipe_id": "cae6dcbe-...",
  "source": "recipenlg",
  "enrichment_status": "validated",
  "tier": 1,
  "tier_assigned_at": "2026-04-12T...",
  "ingredient_count": 5,
  "step_count": 7,
  "enrichment_flags": {
    "has_parsed_ingredients": true,
    "has_normalised_units": true,
    "has_dietary_flags": true,
    "has_cuisine_tag": true,
    "has_real_description": true,
    "has_llm_flavor_tags": true,
    "has_nutrition": false,
    "has_embedding": true
  },
  "provenance": {
    "description": {"source": "llm_mistral", "confidence": 0.82, "method": "mistral-7b-instruct-v0.3"},
    "cuisine_tags": {"source": "rule_deterministic", "confidence": 0.95, "method": "cuisine-lookup-v2"},
    "dietary_flags": {"source": "rule_deterministic", "confidence": 0.90, "method": "ingredient-flag-rules-v1"},
    "nutrition_per_serving": {"source": "unknown", "confidence": 0.0}
  },
  "data": {
    "title": "Shrimp Scampi I.E.S.Jjgf65a",
    "description": "A classic American-Italian shrimp scampi prepared under the broiler...",
    "cuisine_tags": ["American", "Italian-American"],
    "flavor_tags": ["garlicky", "rich", "herbaceous"],
    "texture_tags": ["tender"],
    "dietary_flags": {"contains_shellfish": true, "is_gluten_free": true, ...},
    "nutrition_per_serving": null
  }
}
```

Note: `nutrition_per_serving` is honest null — not fabricated.

---

## What RAG Retrieval May Rely On

The RAG retrieval layer **must only query recipes with `tier = 1`**. It may assert:

- `title` is a real name (not a slug/stub)
- `description` is ≥ 80 chars and human-readable
- `cuisine_tags` and `course_tags` are populated
- `dietary_flags` reflects at least one deterministic enrichment pass
- `embedding_text` was computed post-enrichment, not from raw stub data
- `nutrition_per_serving` may be `null` — the LLM must say "nutrition not available" not invent values

---

## What Must Not Be Touched

| Resource | Constraint |
|---|---|
| `raw_ingredients_text` | Immutable after ingest. Never overwrite. |
| `data->title` (CAT-A) | Immutable. Title cleaning goes into `title_normalized`. |
| `nutrition_per_serving` (CAT-C) | Only USDA/OFF scripts may write this. |
| `source_tier` column | Legacy — not used for pipeline decisions. Read `tier` instead. |
| Tier-1 embeddings | Do not re-embed unless `enrichment_flags.has_embedding = false`. |

---

## Remaining Gaps (for next agent)

1. **Nutrition enrichment script** (`enrich_nutrition_usda.py`) — not yet implemented.
2. **LLM confidence tagging** — current `enrich_recipes_fast.py` does not write confidence back to provenance; extend it.
3. **Stub description detector** — `tier_profile.py` has basic heuristics; improve with a regex-based classifier.
4. **Deduplication** — `title_normalized` column is ready; dedup script not yet written.
5. **Tier-1 embedding filter** — `repair_embeddings_v2.py` embeds all records; add `WHERE tier = 1` filter.
