"""
Stage 3: Retriever  —  Experiment A: Multi-Vector Retrieval

Root-cause hypothesis:
    A single enriched-query embedding loses signal when the query blends
    several orthogonal facets (cuisine, ingredients, mood, occasion).  A
    recipe that nails the ingredient match but uses a different cuisine will
    score mediocrely on a combined vector and might fall below the candidate
    cut.  Decomposing the query into up to four independent facet embeddings
    and fusing per-recipe scores with Reciprocal Rank Fusion (RRF) lets each
    facet vote independently — the combined ranking surfaces recipes that
    excel on ANY facet, not just the centroid.

What changed vs. baseline (retriever.py):
    1. `_build_facet_queries` — decomposes the enriched query + QueryOntology
       into up to four named sub-queries (ingredients, cuisine, mood_occasion,
       full), each embedded separately.  Falls back to single-vector if fewer
       than two facets are non-trivial.
    2. `_rrF_fuse` — Reciprocal Rank Fusion (k=60) over per-facet ranked lists.
       Produces a single fused score per entity_id.
    3. `retrieve_recipes` — unchanged signature; internally calls the new helpers
       instead of embedding a single query string.  Adds `_retrieval_method` key
       to each result dict for debug inspection.

All other code (hard filters, Supabase REST, cosine similarity, parsing) is
identical to the baseline so this file can be swapped in/out without touching
any other pipeline stage.

Combination note:
    The `_RETRIEVAL_METHOD` constant at the top can be set to "multi" (default)
    or "single" to toggle between approaches without a code change, making it
    easy to A/B test at runtime and to keep the baseline measurable on the
    same branch.
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any

import httpx

from config import settings
from models.fused_ontology import RetrievalContext
from models.query_ontology import QueryOntology
from services.embeddings import generate_embedding

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SUPABASE_REST_BASE = f"{settings.SUPABASE_URL}/rest/v1"
DEFAULT_TOP_K = 20
_EMBEDDINGS_PAGE_LIMIT = 1000

# Toggle: "multi" = multi-vector RRF | "single" = baseline single-vector
_RETRIEVAL_METHOD = "multi"

# RRF constant — higher value rewards rank position less aggressively
_RRF_K = 60

_TABLE_CONFIG = {
    "mock": {
        "recipes": ["recipes"],
        "embeddings": ["embeddings"],
    },
    "open": {
        "recipes": ["recipes_open"],
        "embeddings": ["embeddings_open"],
    },
    "combined": {
        "recipes": ["recipes", "recipes_open"],
        "embeddings": ["embeddings", "embeddings_open"],
    },
}


def _get_tables() -> dict[str, list[str]]:
    source = getattr(settings, "DATA_SOURCE", "mock").lower()
    config = _TABLE_CONFIG.get(source)
    if config is None:
        logger.warning("Unknown DATA_SOURCE '%s', falling back to 'mock'", source)
        config = _TABLE_CONFIG["mock"]
    return config


# ---------------------------------------------------------------------------
# Low-level Supabase REST helpers  (unchanged from baseline)
# ---------------------------------------------------------------------------

def _rest_headers() -> dict[str, str]:
    return settings.supabase_rest_headers


async def _fetch_all_embeddings() -> list[dict]:
    tables = _get_tables()
    embedding_tables = tables["embeddings"]
    all_rows: list[dict] = []

    async with httpx.AsyncClient(timeout=45.0) as client:
        for table_name in embedding_tables:
            url = (
                f"{SUPABASE_REST_BASE}/{table_name}"
                f"?select=id,entity_id,embedding"
                f"&entity_type=eq.recipe"
                f"&limit={_EMBEDDINGS_PAGE_LIMIT}"
            )
            resp = await client.get(url, headers=_rest_headers())
            if resp.status_code != 200:
                logger.warning(
                    "Failed to fetch embeddings from %s: %s %s",
                    table_name, resp.status_code, resp.text[:200],
                )
                continue
            rows = resp.json()
            for row in rows:
                row["_source_table"] = table_name.replace("embeddings", "recipes")
            all_rows.extend(rows)

    logger.debug("Total embeddings fetched: %d", len(all_rows))
    return all_rows


async def _fetch_recipes_by_ids(
    entity_ids: list[str],
    table_name: str = "recipes",
) -> list[dict]:
    if not entity_ids:
        return []
    ids_str = ",".join(entity_ids)
    url = (
        f"{SUPABASE_REST_BASE}/{table_name}"
        f"?select=recipe_id,data,source,source_tier"
        f"&recipe_id=in.({ids_str})"
    )
    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.get(url, headers=_rest_headers())
    if resp.status_code != 200:
        logger.warning(
            "Failed to fetch recipes from %s: %s %s",
            table_name, resp.status_code, resp.text[:200],
        )
        return []
    return resp.json()


# ---------------------------------------------------------------------------
# Math helpers  (unchanged from baseline)
# ---------------------------------------------------------------------------

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _parse_embedding(raw: Any) -> list[float] | None:
    if isinstance(raw, list):
        return [float(v) for v in raw]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [float(v) for v in parsed]
        except (json.JSONDecodeError, ValueError):
            pass
        try:
            cleaned = raw.strip().lstrip("[").rstrip("]")
            return [float(v) for v in cleaned.split(",") if v.strip()]
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------------------
# Hard filter  (unchanged from baseline)
# ---------------------------------------------------------------------------

def _passes_hard_filters(
    recipe_data: dict,
    hard_filters: list[dict],
) -> tuple[bool, str | None]:
    for flt in hard_filters:
        ftype = flt.get("type")

        if ftype == "exclude_ingredient":
            ingredient_label = (flt.get("value") or "").lower()
            if not ingredient_label:
                continue
            ingredients = recipe_data.get("ingredients") or []
            for ing in ingredients:
                name = (ing.get("name") if isinstance(ing, dict) else str(ing)).lower()
                if ingredient_label in name:
                    return False, f"Contains excluded ingredient: {ingredient_label}"
            dietary_tags = [t.lower() for t in (recipe_data.get("dietary_tags") or [])]
            if ingredient_label in " ".join(dietary_tags):
                return False, f"Dietary tag conflict: {ingredient_label}"

        elif ftype == "dietary_flag":
            flag_name = flt.get("value")
            required = flt.get("required", True)
            if flag_name:
                dietary_flags = recipe_data.get("dietary_flags") or {}
                actual_val = (
                    dietary_flags.get(flag_name, False)
                    if isinstance(dietary_flags, dict)
                    else getattr(dietary_flags, flag_name, False)
                )
                if bool(actual_val) != bool(required):
                    return False, f"Dietary flag '{flag_name}' required={required}, got={actual_val}"

        elif ftype == "max_time_min":
            max_time = flt.get("value")
            if max_time is not None:
                recipe_time = recipe_data.get("time_total_min")
                if recipe_time is not None and int(recipe_time) > int(max_time):
                    return False, f"Time {recipe_time} min exceeds limit {max_time} min"

        elif ftype == "exclude_cuisine":
            excluded_cuisine = (flt.get("value") or "").lower()
            recipe_cuisines = [c.lower() for c in (recipe_data.get("cuisine_tags") or [])]
            if any(excluded_cuisine in c for c in recipe_cuisines):
                return False, f"Cuisine '{excluded_cuisine}' is excluded"

    return True, None


# ---------------------------------------------------------------------------
# NEW: Facet query decomposition
# ---------------------------------------------------------------------------

def _build_facet_queries(
    enriched_query: str,
    query_ontology: QueryOntology | None = None,
) -> dict[str, str]:
    """
    Decompose the query into named facet sub-strings, each intended to be
    embedded separately.

    Returns a dict of {facet_name: query_string}.  The "full" facet is always
    present (= the enriched query) and serves as the RRF tie-breaker when
    facet-specific signals are missing.

    Facets:
        full           — the full enriched query (always present)
        ingredients    — ingredient-focused sub-query (present if ≥1 ingredient)
        cuisine        — cuisine-focused sub-query (present if cuisine specified)
        mood_occasion  — mood/occasion sub-query (present if either is specified)
    """
    facets: dict[str, str] = {"full": enriched_query}

    if query_ontology is None:
        return facets

    ea = query_ontology.eat_in_attributes
    if ea is None:
        return facets

    # Ingredients facet
    if ea.desired_ingredients:
        ing_str = ", ".join(ea.desired_ingredients[:8])
        facets["ingredients"] = f"recipe with ingredients: {ing_str}"

    # Cuisine facet
    if ea.desired_cuisine:
        facets["cuisine"] = f"{ea.desired_cuisine} recipe cuisine cooking"

    # Mood / occasion facet
    mood_parts: list[str] = []
    if ea.mood:
        mood_parts.append(ea.mood)
    if ea.occasion:
        mood_parts.append(ea.occasion)
    if query_ontology.inferred_mood:
        mood_parts.append(query_ontology.inferred_mood)
    if mood_parts:
        facets["mood_occasion"] = " ".join(mood_parts) + " food meal"

    return facets


# ---------------------------------------------------------------------------
# NEW: Reciprocal Rank Fusion
# ---------------------------------------------------------------------------

def _rrf_fuse(
    ranked_lists: list[list[tuple[float, str]]],
    k: int = _RRF_K,
) -> list[tuple[float, str]]:
    """
    Fuse multiple ranked lists using Reciprocal Rank Fusion.

    Args:
        ranked_lists: Each element is a list of (score, entity_id) sorted
                      by score descending.  Score is only used for ordering.
        k: RRF constant (default 60, per the original Cormack et al. paper).

    Returns:
        List of (rrf_score, entity_id) sorted by rrf_score descending.
    """
    rrf_scores: dict[str, float] = {}

    for ranked in ranked_lists:
        for rank, (_, entity_id) in enumerate(ranked, start=1):
            rrf_scores[entity_id] = rrf_scores.get(entity_id, 0.0) + 1.0 / (k + rank)

    fused = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    # Return as (score, entity_id) for compatibility with downstream code
    return [(score, eid) for eid, score in fused]


# ---------------------------------------------------------------------------
# Similarity scoring (shared)
# ---------------------------------------------------------------------------

def _score_all_embeddings(
    query_embedding: list[float],
    all_embeddings: list[dict],
) -> list[tuple[float, str]]:
    """Cosine similarity of query_embedding against all_embeddings. Returns sorted list."""
    scored: list[tuple[float, str]] = []
    for row in all_embeddings:
        entity_id = str(row.get("entity_id") or "")
        raw_emb = row.get("embedding")
        if not entity_id or raw_emb is None:
            continue
        emb_vec = _parse_embedding(raw_emb)
        if emb_vec is None or len(emb_vec) == 0:
            continue
        sim = _cosine_similarity(query_embedding, emb_vec)
        scored.append((sim, entity_id))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


# ---------------------------------------------------------------------------
# Main retrieval function
# ---------------------------------------------------------------------------

async def retrieve_recipes(
    query_text: str,
    retrieval_context: RetrievalContext,
    top_k: int = DEFAULT_TOP_K,
    # Exp A: accepts the full QueryOntology for facet decomposition.
    # This parameter is optional and defaults to None so the function
    # signature remains backward-compatible with the baseline caller.
    query_ontology: QueryOntology | None = None,
) -> list[dict]:
    """
    Stage 3 — Experiment A: Multi-Vector Retrieval with RRF fusion.

    When _RETRIEVAL_METHOD == "multi" (default):
        1. Decompose query into facets (ingredients, cuisine, mood_occasion, full)
        2. Embed each facet independently (async, sequential to respect rate limits)
        3. Score all recipe embeddings against each facet
        4. Fuse per-facet ranked lists with Reciprocal Rank Fusion
        5. Use fused ranks to select top candidates before hard filtering

    When _RETRIEVAL_METHOD == "single":
        Falls back to single-vector baseline behaviour for direct comparison.

    Args:
        query_text: Enriched query string (same as baseline).
        retrieval_context: Fusion output with hard_filters.
        top_k: Number of recipes to return after filtering.
        query_ontology: Optional — used for facet decomposition.  If None,
                        falls back gracefully to single-vector mode.

    Returns:
        List of recipe dicts augmented with '_similarity', '_entity_id',
        '_retrieval_method', and '_facet_scores' keys.
    """
    logger.info(
        "Stage 3 (exp/a): retrieving recipes | method=%s | query=%s",
        _RETRIEVAL_METHOD,
        query_text[:80],
    )

    # Fetch all embeddings once (shared across all facets)
    try:
        all_embeddings = await _fetch_all_embeddings()
    except Exception as exc:
        logger.error("Failed to fetch embeddings: %s", exc)
        raise

    if not all_embeddings:
        logger.warning("No embeddings found in database")
        return []

    # --- Build entity_id → source table mapping (needed later) ---
    entity_source_table: dict[str, str] = {}
    for row in all_embeddings:
        eid = str(row.get("entity_id") or "")
        if eid:
            entity_source_table[eid] = row.get("_source_table", "recipes")

    # ----------------------------------------------------------------
    # Path A: Multi-vector with RRF
    # ----------------------------------------------------------------
    if _RETRIEVAL_METHOD == "multi" and query_ontology is not None:
        facets = _build_facet_queries(query_text, query_ontology)

        if len(facets) < 2:
            # Not enough facets to justify multi-vector — fall through to single
            logger.debug("Exp A: only 1 facet found, falling back to single-vector")
        else:
            # Embed each facet
            facet_ranked: list[list[tuple[float, str]]] = []
            facet_embeddings: dict[str, list[float]] = {}

            for facet_name, facet_query in facets.items():
                try:
                    emb = await generate_embedding(facet_query)
                    facet_embeddings[facet_name] = emb
                    ranked = _score_all_embeddings(emb, all_embeddings)
                    facet_ranked.append(ranked)
                    logger.debug(
                        "Exp A: facet '%s' scored %d recipes (top=%.3f)",
                        facet_name,
                        len(ranked),
                        ranked[0][0] if ranked else 0.0,
                    )
                except Exception as exc:
                    logger.warning("Exp A: failed to embed facet '%s': %s", facet_name, exc)

            if len(facet_ranked) >= 2:
                # Fuse
                fused = _rrf_fuse(facet_ranked, k=_RRF_K)

                # Build per-entity cosine scores from the "full" facet for the
                # _similarity field (used downstream by the ranker as a signal)
                full_emb = facet_embeddings.get("full")
                full_scored: dict[str, float] = {}
                if full_emb:
                    for sim, eid in _score_all_embeddings(full_emb, all_embeddings):
                        full_scored[eid] = sim

                # Build per-entity per-facet cosine score dict for debug
                facet_scores_by_entity: dict[str, dict[str, float]] = {}
                for facet_name, facet_emb in facet_embeddings.items():
                    for sim, eid in _score_all_embeddings(facet_emb, all_embeddings):
                        facet_scores_by_entity.setdefault(eid, {})[facet_name] = round(sim, 4)

                candidate_count = min(top_k * 4, len(fused))
                top_candidates = fused[:candidate_count]

                logger.info(
                    "Exp A RRF: %d facets fused → %d candidates (top rrf=%.4f)",
                    len(facet_ranked),
                    len(top_candidates),
                    top_candidates[0][0] if top_candidates else 0.0,
                )

                # Fetch recipe docs
                top_entity_ids = [eid for _, eid in top_candidates]
                sim_map = {eid: rrf_score for rrf_score, eid in top_candidates}

                from collections import defaultdict
                ids_by_table: dict[str, list[str]] = defaultdict(list)
                for eid in top_entity_ids:
                    table = entity_source_table.get(eid, "recipes")
                    ids_by_table[table].append(eid)

                all_recipe_rows: list[dict] = []
                for table_name, table_ids in ids_by_table.items():
                    for i in range(0, len(table_ids), 50):
                        batch_ids = table_ids[i: i + 50]
                        try:
                            rows = await _fetch_recipes_by_ids(batch_ids, table_name=table_name)
                            all_recipe_rows.extend(rows)
                        except Exception as exc:
                            logger.error("Failed to fetch recipe batch: %s", exc)

                recipe_lookup: dict[str, dict] = {
                    str(r.get("recipe_id") or ""): r
                    for r in all_recipe_rows
                    if r.get("recipe_id")
                }

                results: list[dict] = []
                for rrf_score, entity_id in top_candidates:
                    if len(results) >= top_k:
                        break
                    row = recipe_lookup.get(entity_id)
                    if row is None:
                        continue
                    recipe_data = row.get("data") or {}
                    if isinstance(recipe_data, str):
                        try:
                            recipe_data = json.loads(recipe_data)
                        except json.JSONDecodeError:
                            continue

                    passes, reason = _passes_hard_filters(
                        recipe_data, retrieval_context.hard_filters
                    )
                    if not passes:
                        logger.debug("Recipe %s filtered out: %s", entity_id, reason)
                        continue

                    recipe_data["_similarity"] = full_scored.get(entity_id, rrf_score)
                    recipe_data["_rrf_score"] = round(rrf_score, 6)
                    recipe_data["_entity_id"] = entity_id
                    recipe_data["_source"] = row.get("source", "unknown")
                    recipe_data["_source_tier"] = row.get("source_tier", 0)
                    recipe_data["_retrieval_method"] = "multi_rrf"
                    recipe_data["_facet_scores"] = facet_scores_by_entity.get(entity_id, {})

                    results.append(recipe_data)

                logger.info(
                    "Stage 3 (exp/a) complete: %d recipes returned via multi-vector RRF",
                    len(results),
                )
                return results

    # ----------------------------------------------------------------
    # Path B: Single-vector fallback (identical to baseline)
    # ----------------------------------------------------------------
    logger.debug("Exp A: using single-vector fallback")
    try:
        query_embedding = await generate_embedding(query_text)
    except Exception as exc:
        logger.error("Failed to generate query embedding: %s", exc)
        raise

    scored = _score_all_embeddings(query_embedding, all_embeddings)
    candidate_count = min(top_k * 4, len(scored))
    top_candidates = scored[:candidate_count]

    sim_map = {eid: sim for sim, eid in top_candidates}
    top_entity_ids = [eid for _, eid in top_candidates]

    from collections import defaultdict
    ids_by_table: dict[str, list[str]] = defaultdict(list)
    for eid in top_entity_ids:
        table = entity_source_table.get(eid, "recipes")
        ids_by_table[table].append(eid)

    all_recipe_rows: list[dict] = []
    for table_name, table_ids in ids_by_table.items():
        for i in range(0, len(table_ids), 50):
            batch_ids = table_ids[i: i + 50]
            try:
                rows = await _fetch_recipes_by_ids(batch_ids, table_name=table_name)
                all_recipe_rows.extend(rows)
            except Exception as exc:
                logger.error("Failed to fetch recipe batch: %s", exc)

    recipe_lookup: dict[str, dict] = {
        str(r.get("recipe_id") or ""): r
        for r in all_recipe_rows
        if r.get("recipe_id")
    }

    results: list[dict] = []
    for sim, entity_id in top_candidates:
        if len(results) >= top_k:
            break
        row = recipe_lookup.get(entity_id)
        if row is None:
            continue
        recipe_data = row.get("data") or {}
        if isinstance(recipe_data, str):
            try:
                recipe_data = json.loads(recipe_data)
            except json.JSONDecodeError:
                continue

        passes, reason = _passes_hard_filters(recipe_data, retrieval_context.hard_filters)
        if not passes:
            continue

        recipe_data["_similarity"] = sim
        recipe_data["_entity_id"] = entity_id
        recipe_data["_source"] = row.get("source", "unknown")
        recipe_data["_source_tier"] = row.get("source_tier", 0)
        recipe_data["_retrieval_method"] = "single_vector"

        results.append(recipe_data)

    logger.info(
        "Stage 3 (exp/a) complete: %d recipes returned via single-vector fallback",
        len(results),
    )
    return results
