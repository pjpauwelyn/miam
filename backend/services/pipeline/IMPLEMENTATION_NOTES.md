# Eat In Pipeline — Implementation Notes

## Overview

The miam Eat In pipeline is a 6-stage sequential processing chain that converts
a natural-language food query into ranked recipe recommendations with a
generated natural-language response.

All files live in `/backend/services/pipeline/`.

---

## Files Created

| File | Stage | Role |
|------|-------|------|
| `__init__.py` | — | Package init; exports `run_eat_in_pipeline` |
| `query_extractor.py` | 1+2 | LLM-based query parsing → `QueryOntology` |
| `fusion.py` | 2b | Pure-Python ontology fusion → `RetrievalContext` |
| `retriever.py` | 3 | Semantic search via Supabase REST API + local cosine similarity |
| `ranker.py` | 4 | 7-factor weighted ranking; returns top 5 |
| `refinement_agent.py` | 5 | LLM-based quality gate; produces ONLY input to Stage 6 |
| `response_generator.py` | 6 | LLM-based final response generation |
| `eat_in_pipeline.py` | Orchestrator | Coordinates all stages with graceful degradation |

---

## Design Decisions

### Critical rule enforced: Generation agent separation
Stage 5 (refinement_agent) is the **only** path through which information
reaches Stage 6 (response_generator). The generator never receives raw
retrieved documents, raw recipe JSON, or database output. This is enforced
structurally — `generate_response()` accepts `refined_context: str` and
`ranked_recipes: list[dict]` but only the string is passed to the LLM.
The `ranked_recipes` parameter exists solely for fallback metadata if the
LLM call fails.

### Supabase REST API for retrieval
Direct PostgreSQL is blocked from the sandbox. The retriever uses a two-step
approach:
1. Fetch all 403 recipe embeddings from `embeddings` table via REST
2. Compute cosine similarity locally (fast for 403 vectors)
3. Fetch top-K recipe documents by `recipe_id=in.(...)` batch query

This avoids pgvector RPC functions and is correct for the current corpus size.

### LLM routing: all calls via llm_router.py
- Stage 1+2 uses `LLMOperation.QUERY_EXTRACTION` → `mistral-small-latest`
- Stage 5 uses `LLMOperation.REFINEMENT_AGENT` → `mistral-small-latest`
- Stage 6 uses `LLMOperation.RESPONSE_GENERATION` → `mistral-small-latest`
- No model names are hardcoded in pipeline files

### Fusion: pure Python, 7 steps
All fusion logic is deterministic. The 7-step algorithm covers:
- Hard stop safety gate (dietary restrictions → hard_filters)
- Base weight vector from `DimensionMeta.weight` (WEIGHT_MAP applied)
- Query centrality modulation (desired cuisine, ingredients, time → boosts)
- Soft preference blending (cuisine affinities, flavor prefs)
- Logical relationship enforcement (AMPLIFIES, ATTENUATES)
- Context modulation (time of day inferred from UTC if no session context)
- Conflict resolution pass (HONOR_PROFILE, SHOW_WARNING, ASK_USER)

### Ranker: 7 factors, weights sum to 1.0

| Factor | Weight | Notes |
|--------|--------|-------|
| Ingredient overlap (Jaccard) | 0.30 | Substring matching for EU English names |
| Dietary compliance | 0.25 | Hard stops → 0.0 gate; soft stops → penalty |
| Cuisine affinity | 0.15 | Profile affinities or explicit query cuisine |
| Difficulty match | 0.10 | Skill ceiling vs recipe difficulty (1–5) |
| Time fit | 0.10 | Profile time budget or query constraint |
| Flavor affinity | 0.05 | Recipe flavor_tags vs profile flavor preferences |
| Novelty bonus | 0.05 | Uncommon cuisines + adventurousness score |

Tier labels: `full_match` (≥0.80), `close_match` (0.50–0.79), `stretch_pick` (<0.50)

---

## Graceful Degradation

Each stage in `eat_in_pipeline.py` is wrapped in try/except:

- **Stage 0 (profile)**: Falls back to default UserProfile if load fails
- **Stage 1+2 (extraction)**: LLM retried once at temperature=0; then minimal QueryOntology
- **Stage 2b (fusion)**: Falls back to empty RetrievalContext
- **Stage 3 (retrieval)**: Hard failure (no fallback possible); returns error response
- **Stage 4 (ranking)**: Falls back to retrieval order (top 5)
- **Stage 5 (refinement)**: Falls back to deterministic context builder
- **Stage 6 (generation)**: LLM retried once at temperature=0; then title-list fallback

The `pipeline_status` field in the response indicates: `ok`, `partial`, `error`,
`no_results`, `blocked`, or `clarification_needed`.

---

## Known Limitations

1. **Embedding fetch latency**: Fetching all 403 embeddings on every query adds
   ~500ms. For production, this should be replaced with a Supabase RPC using
   `pgvector` cosine similarity, or embeddings should be cached in memory.

2. **profile_service.py stubs**: The existing `fuse_ontologies` in
   `profile_service.py` references non-existent model fields (old draft API).
   The pipeline uses its own `fusion.py` instead. The stub in `profile_service.py`
   is preserved as-is to avoid breaking other code.

3. **LLM timeout**: `mistral-small-latest` has a 5-second timeout in the router.
   For complex queries, Stages 1+2 may occasionally time out and fall back to the
   minimal QueryOntology. Consider increasing timeout for production.

4. **Ingredient matching**: Uses simple substring matching. A production system
   should use the `synonym_resolver.py` service for normalisation.

---

## Usage

```python
from services.pipeline.eat_in_pipeline import run_eat_in_pipeline

result = await run_eat_in_pipeline(
    raw_query="quick weeknight pasta with vegetables",
    user_id="550e8400-e29b-41d4-a716-446655440000",
    session_id=None,
)

print(result["generated_text"])
for recipe in result["results"]:
    print(recipe["title"], recipe["match_score"], recipe["match_tier"])
```

---

## Test Results (import + functional tests)

All 12 modules import without errors. Functional tests confirm:
- Fusion correctly applies hard stops, dietary spectrum, cuisine exclusions, and time constraints
- Ranker scores vegetarian Italian pasta at `full_match` (0.95) vs chicken schnitzel at `stretch_pick` (0.28) when given a vegetarian Italian query
- Factor weights sum exactly to 1.0
- Flavor mismatch conflict detected when Thai cuisine requested by a user who hates spicy food
