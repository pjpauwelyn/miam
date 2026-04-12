# MIAM Recipe Schema Contract

**Version:** 2.1 (has_course_tag + rag_embedding_version)
**Effective from:** 2026-04-12
**Changelog:**
- v2.1 (2026-04-12): Added `has_course_tag` to Tier-1 criteria and enrichment_flags;
  added `rag_embedding_version` field; added `promotion_score` column;
  tightened Remaining Gaps list with concrete owner/blocker per item.
- v2.0 (2026-04-12): Initial provenance-aware schema.
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

| Criterion | Threshold | Field | Tracked in flag |
|---|---|---|---|
| Title present | len >= 5 chars | `data->>'title'` | — |
| Parsed ingredients | >= 2 items | `ingredient_count` (computed col) | `has_parsed_ingredients` |
| Structured steps | >= 2 steps | `step_count` (computed col) | — |
| Real description | >= 80 chars, not a stub phrase | `data->>'description'` | `has_real_description` |
| Cuisine classified | non-empty array | `data->'cuisine_tags'` | `has_cuisine_tag` |
| Course classified | non-empty array | `data->'course_tags'` | `has_course_tag` |
| Dietary flags enriched | at least one flag is True | `data->'dietary_flags'` | `has_dietary_flags` |
| Pipeline stage | deterministic_enriched, llm_enriched, or validated | `enrichment_status` | — |
| Description confidence | >= 0.6 (if LLM-produced) | `provenance->description->confidence` | — |

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
**Writes (CAT-E only):** `tier`, `tier_assigned_at`, `enrichment_flags`, `provenance` (seed only — never overwrites)  
**Must not touch:** data JSONB content fields  
**Frequency:** after every enrichment stage; safe to run continuously  

### Stage 7 — Embedding

**Script:** `repair_embeddings_v2.py` (extended for Tier-1 filter)  
**Reads:** Tier-1 records (`tier = 1`)  
**Writes:** `embeddings_open` table  
**Sets:** `enrichment_flags.has_embedding = true`, `enrichment_flags.rag_embedding_version = '<model-slug>'`  
**Must not touch:** `recipes_open.data`  

---

## DB Column Map

The `recipes_open` table stores content in `data` JSONB plus these typed columns:

| Column | Type | Purpose | Added in |
|---|---|---|---|
| `recipe_id` | UUID PK | Stable identifier | baseline |
| `data` | JSONB | Full RecipeDocument content fields | baseline |
| `source` | TEXT | Dataset name (e.g. `recipenlg`) | baseline |
| `source_tier` | INT | Legacy — superseded by `tier` column | baseline |
| `enrichment_status` | TEXT | Stage gate | migration 001 |
| `tier` | INT | Quality tier (0–3) | migration 001 |
| `tier_assigned_at` | TIMESTAMPTZ | Last tier computation | migration 001 |
| `provenance` | JSONB | Per-field-group provenance map | migration 001 |
| `enrichment_flags` | JSONB | Boolean completion flags (see table below) | migration 001 |
| `title_normalized` | TEXT (generated) | For dedup / slug | migration 001 |
| `ingredient_count` | INT (generated) | From `data->ingredients` | migration 001 |
| `step_count` | INT (generated) | From `data->steps` | migration 001 |
| `promotion_blocked_reason` | TEXT | Human/system override | migration 001 |
| `promotion_score` | INT (generated) | 0-100 deterministic readiness score | migration 002 |
| `created_at` | TIMESTAMPTZ | Ingest timestamp | baseline |

### enrichment_flags schema

| Flag key | Type | Meaning | Tier-1 criterion? |
|---|---|---|---|
| `has_parsed_ingredients` | bool | >= 1 parsed ingredient in `data->ingredients` | Yes (>= 2 required) |
| `has_normalised_units` | bool | At least one ingredient has a recognised metric unit | No |
| `has_dietary_flags` | bool | At least one dietary flag is True | Yes |
| `has_cuisine_tag` | bool | `data->cuisine_tags` non-empty | Yes |
| `has_course_tag` | bool | `data->course_tags` non-empty | Yes |
| `has_real_description` | bool | description >= 80 chars and not a stub phrase | Yes |
| `has_llm_flavor_tags` | bool | `data->flavor_tags` non-empty | No |
| `has_nutrition` | bool | `data->nutrition_per_serving` not null | No |
| `has_embedding` | bool | Vector exists in `embeddings_open` | Not for Tier-1, required for RAG |
| `rag_embedding_version` | string\|null | Model slug used for current embedding | — |

### promotion_score formula

```
+30  has_real_description
+20  has_cuisine_tag
+20  has_course_tag
+15  has_dietary_flags
+10  has_llm_flavor_tags
+5   has_nutrition
───
100  maximum
```

A record with `promotion_score >= 85` AND `tier = 1` is the ideal RAG candidate.

---

## Before / After Record Comparison

### BEFORE (raw ingest state)

```json
{
  "recipe_id": "cae6dcbe-...",
  "source": "recipenlg",
  "enrichment_status": "raw",
  "tier": 0,
  "tier_assigned_at": null,
  "ingredient_count": 0,
  "step_count": 0,
  "enrichment_flags": {},
  "provenance": {},
  "promotion_score": 0,
  "data": {
    "title": "Shrimp Scampi I.E.S.Jjgf65a",
    "description": "A recipe for Shrimp Scampi I.E.S.Jjgf65a.",
    "cuisine_tags": ["Other"],
    "course_tags": [],
    "flavor_tags": [],
    "dietary_flags": {},
    "nutrition_per_serving": null
  }
}
```

Problems: stub description, vague cuisine, no course tags, no flavor/texture tags,
no dietary enrichment, no nutrition, no provenance stub, no tier.

### AFTER (Tier-1 / validated state)

```json
{
  "recipe_id": "cae6dcbe-...",
  "source": "recipenlg",
  "enrichment_status": "validated",
  "tier": 1,
  "tier_assigned_at": "2026-04-12T14:00:00Z",
  "ingredient_count": 5,
  "step_count": 7,
  "promotion_score": 85,
  "enrichment_flags": {
    "has_parsed_ingredients": true,
    "has_normalised_units": true,
    "has_dietary_flags": true,
    "has_cuisine_tag": true,
    "has_course_tag": true,
    "has_real_description": true,
    "has_llm_flavor_tags": true,
    "has_nutrition": false,
    "has_embedding": true,
    "rag_embedding_version": "text-embedding-3-small-v1"
  },
  "provenance": {
    "title":         {"source": "recipenlg_raw",    "confidence": 0.5,  "method": "ingest"},
    "description":   {"source": "llm_mistral",      "confidence": 0.82, "method": "mistral-7b-instruct-v0.3"},
    "cuisine_tags":  {"source": "rule_deterministic","confidence": 0.95, "method": "cuisine-lookup-v2"},
    "course_tags":   {"source": "rule_deterministic","confidence": 0.90, "method": "course-keyword-rules-v1"},
    "dietary_flags": {"source": "rule_deterministic","confidence": 0.90, "method": "ingredient-flag-rules-v1"},
    "flavor_tags":   {"source": "llm_mistral",      "confidence": 0.75, "method": "mistral-7b-instruct-v0.3"},
    "nutrition_per_serving": {"source": "unknown",  "confidence": 0.0,  "method": null}
  },
  "data": {
    "title": "Shrimp Scampi I.E.S.Jjgf65a",
    "description": "A classic American-Italian shrimp scampi prepared under the broiler with a generous amount of garlic and lemon butter. Crisp breadcrumbs add texture to the tender, juicy shrimp.",
    "cuisine_tags": ["American", "Italian-American"],
    "course_tags": ["main"],
    "flavor_tags": ["garlicky", "rich", "herbaceous"],
    "texture_tags": ["tender", "crispy"],
    "dietary_flags": {"contains_shellfish": true, "is_gluten_free": false},
    "nutrition_per_serving": null
  }
}
```

Note: `nutrition_per_serving` is an honest null — not fabricated. The RAG layer
must surface this fact rather than inventing calorie values.

---

## What RAG Retrieval May Rely On

The RAG retrieval layer **must only query recipes with `tier = 1`**. It may assert:

- `title` is a real name (not a slug/stub)
- `description` is >= 80 chars and human-readable
- `cuisine_tags` and `course_tags` are populated
- `dietary_flags` reflects at least one deterministic enrichment pass
- `embedding_text` was computed post-enrichment, not from raw stub data
- `rag_embedding_version` tells you which model produced the vector — if it differs
  from the active model, treat the embedding as stale
- `nutrition_per_serving` may be `null` — the LLM must say "nutrition not available"
  rather than invent values
- `promotion_score` gives a deterministic quality rank within Tier 1

---

## What Must Not Be Touched

| Resource | Constraint |
|---|---|
| `raw_ingredients_text` | Immutable after ingest. Never overwrite. |
| `data->title` (CAT-A) | Immutable. Title cleaning goes into `title_normalized`. |
| `nutrition_per_serving` (CAT-C) | Only USDA/OFF scripts may write this. |
| `source_tier` column | Legacy — not used for pipeline decisions. Read `tier` instead. |
| `enrichment_flags.has_embedding` | Only `repair_embeddings_v2.py` may set this to true. |
| `enrichment_flags.rag_embedding_version` | Only `repair_embeddings_v2.py` may write this. |
| Tier-1 embeddings | Do not re-embed unless `rag_embedding_version` diverges from active model. |

---

## Remaining Gaps (concrete blockers for next agent)

| Gap | Owner script | Blocker |
|---|---|---|
| `has_course_tag = false` on ~90%+ records | new course-tag rule enrichment pass | `course_tags` not populated during ingest |
| Nutrition enrichment | `enrich_nutrition_usda.py` (not yet written) | USDA API key + ingredient normalisation |
| LLM confidence write-back | `enrich_recipes_fast.py` | Currently does not set `provenance->description->confidence` |
| Stub description detector | `tier_profile.py` `_is_stub_description()` | Heuristic; needs regex classifier on larger pattern set |
| Deduplication script | new `dedup_by_title.py` | `title_normalized` column ready; script not written |
| Tier-1 embedding filter | `repair_embeddings_v2.py` | Currently embeds all records; add `WHERE tier = 1` |
| `rag_embedding_version` write-back | `repair_embeddings_v2.py` | Not yet set; needed to detect stale embeddings post model upgrade |
