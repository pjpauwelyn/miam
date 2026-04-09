"""
Stage 3: Retriever

Performs semantic search over the recipe corpus using embedding similarity,
then applies hard filters from the RetrievalContext.

Since direct PostgreSQL is blocked from the sandbox, this module uses the
Supabase REST API with a two-step approach:
  1. Fetch all recipe embeddings (403 records) and compute cosine similarity locally
  2. Fetch the recipe data for the top-K matched entity_ids

Function signature:
    async def retrieve_recipes(
        query_text: str,
        retrieval_context: RetrievalContext,
        top_k: int = 20,
    ) -> list[dict]
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any

import httpx

from config import settings
from models.fused_ontology import RetrievalContext
from services.embeddings import generate_embedding

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SUPABASE_REST_BASE = f"{settings.SUPABASE_URL}/rest/v1"
DEFAULT_TOP_K = 20
# Maximum number of embeddings to fetch in one REST call
_EMBEDDINGS_PAGE_LIMIT = 1000

# Table mapping by DATA_SOURCE config
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
    """Get recipe and embedding table names based on DATA_SOURCE config."""
    source = getattr(settings, "DATA_SOURCE", "mock").lower()
    config = _TABLE_CONFIG.get(source)
    if config is None:
        logger.warning("Unknown DATA_SOURCE '%s', falling back to 'mock'", source)
        config = _TABLE_CONFIG["mock"]
    return config


# ---------------------------------------------------------------------------
# Low-level Supabase REST helpers
# ---------------------------------------------------------------------------

def _rest_headers() -> dict[str, str]:
    return settings.supabase_rest_headers


async def _fetch_all_embeddings() -> list[dict]:
    """
    Fetch all recipe embeddings from the configured Supabase embeddings table(s).
    Supports DATA_SOURCE=mock|open|combined.
    Returns list of dicts with keys: id, entity_id, embedding (list[float])
    """
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
            # Tag rows with source table for recipe lookup
            for row in rows:
                row["_source_table"] = table_name.replace("embeddings", "recipes")
            all_rows.extend(rows)
            logger.debug("Fetched %d embeddings from %s", len(rows), table_name)

    logger.debug("Total embeddings fetched: %d", len(all_rows))
    return all_rows


async def _fetch_recipes_by_ids(
    entity_ids: list[str],
    table_name: str = "recipes",
) -> list[dict]:
    """
    Fetch recipe documents from the specified recipes table by recipe_id.
    Returns list of dicts with keys: recipe_id, data (dict), source, source_tier
    """
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
    rows = resp.json()
    return rows


# ---------------------------------------------------------------------------
# Cosine similarity (local computation)
# ---------------------------------------------------------------------------

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _parse_embedding(raw: Any) -> list[float] | None:
    """
    Parse an embedding value that may arrive as:
    - A list of floats (already deserialized)
    - A JSON string "[0.1, 0.2, ...]"
    - A pgvector text representation "[0.1,0.2,...]"
    """
    if isinstance(raw, list):
        return [float(v) for v in raw]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [float(v) for v in parsed]
        except (json.JSONDecodeError, ValueError):
            pass
        # Try stripping brackets and splitting
        try:
            cleaned = raw.strip().lstrip("[").rstrip("]")
            return [float(v) for v in cleaned.split(",") if v.strip()]
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------------------
# Hard filter application
# ---------------------------------------------------------------------------

def _passes_hard_filters(recipe_data: dict, hard_filters: list[dict]) -> tuple[bool, str | None]:
    """
    Apply hard filters to a recipe dict.
    Returns (passes: bool, rejection_reason: str | None).

    The recipe_data is the JSONB 'data' column from the recipes table,
    which is a RecipeDocument-compatible dict.
    """
    for flt in hard_filters:
        ftype = flt.get("type")

        if ftype == "exclude_ingredient":
            ingredient_label = (flt.get("value") or "").lower()
            if not ingredient_label:
                continue
            # Check recipe ingredients list
            ingredients = recipe_data.get("ingredients") or []
            for ing in ingredients:
                if isinstance(ing, dict):
                    name = (ing.get("name") or "").lower()
                elif isinstance(ing, str):
                    name = ing.lower()
                else:
                    continue
                if ingredient_label in name:
                    return False, f"Contains excluded ingredient: {ingredient_label}"
            # Also check dietary_tags (e.g. "contains_pork")
            dietary_tags = [t.lower() for t in (recipe_data.get("dietary_tags") or [])]
            if ingredient_label in " ".join(dietary_tags):
                return False, f"Dietary tag conflict: {ingredient_label}"

        elif ftype == "dietary_flag":
            flag_name = flt.get("value")
            required = flt.get("required", True)
            if flag_name:
                dietary_flags = recipe_data.get("dietary_flags") or {}
                if isinstance(dietary_flags, dict):
                    actual_val = dietary_flags.get(flag_name, False)
                else:
                    actual_val = getattr(dietary_flags, flag_name, False)
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
# Main retrieval function
# ---------------------------------------------------------------------------

async def retrieve_recipes(
    query_text: str,
    retrieval_context: RetrievalContext,
    top_k: int = DEFAULT_TOP_K,
) -> list[dict]:
    """
    Stage 3: Semantic recipe retrieval.

    Steps:
    1. Generate embedding for query_text
    2. Fetch all recipe embeddings from Supabase REST API
    3. Compute cosine similarity locally
    4. Take top candidates (3x top_k for filtering headroom)
    5. Fetch recipe documents for top candidates
    6. Apply hard filters from retrieval_context
    7. Return up to top_k recipes with similarity scores

    Args:
        query_text: The query string to embed (typically the raw user query
                    enriched with key attributes).
        retrieval_context: Fusion output containing hard_filters, etc.
        top_k: Number of recipes to return after filtering.

    Returns:
        List of recipe dicts (from the recipes.data JSONB column),
        each augmented with '_similarity' and '_entity_id' keys.
    """
    logger.info("Stage 3: retrieving recipes for query: %s", query_text[:80])

    # Step 1: Embed query
    try:
        query_embedding = await generate_embedding(query_text)
    except Exception as exc:
        logger.error("Failed to generate query embedding: %s", exc)
        raise

    # Step 2: Fetch all embeddings
    try:
        all_embeddings = await _fetch_all_embeddings()
    except Exception as exc:
        logger.error("Failed to fetch embeddings from Supabase: %s", exc)
        raise

    if not all_embeddings:
        logger.warning("No embeddings found in database")
        return []

    # Step 3: Compute cosine similarity locally
    scored: list[tuple[float, str]] = []  # (similarity, entity_id)
    skipped = 0

    for row in all_embeddings:
        entity_id = str(row.get("entity_id") or "")
        raw_emb = row.get("embedding")
        if not entity_id or raw_emb is None:
            skipped += 1
            continue

        emb_vec = _parse_embedding(raw_emb)
        if emb_vec is None or len(emb_vec) == 0:
            skipped += 1
            continue

        sim = _cosine_similarity(query_embedding, emb_vec)
        scored.append((sim, entity_id))

    if skipped > 0:
        logger.debug("Skipped %d embeddings with parse errors", skipped)

    # Step 4: Sort by similarity descending, take top candidates with headroom
    scored.sort(key=lambda x: x[0], reverse=True)
    candidate_count = min(top_k * 4, len(scored))  # 4x headroom for filtering
    top_candidates = scored[:candidate_count]

    logger.debug(
        "Similarity scoring complete: %d candidates (top sim=%.3f, bottom sim=%.3f)",
        len(top_candidates),
        top_candidates[0][0] if top_candidates else 0.0,
        top_candidates[-1][0] if top_candidates else 0.0,
    )

    # Build entity_id → similarity lookup and track source tables
    sim_map = {eid: sim for sim, eid in top_candidates}
    top_entity_ids = [eid for _, eid in top_candidates]

    # Build entity_id → source table mapping
    entity_source_table: dict[str, str] = {}
    for row in all_embeddings:
        eid = str(row.get("entity_id") or "")
        if eid:
            entity_source_table[eid] = row.get("_source_table", "recipes")

    # Step 5: Fetch recipe documents in batches, grouped by source table
    from collections import defaultdict
    ids_by_table: dict[str, list[str]] = defaultdict(list)
    for eid in top_entity_ids:
        table = entity_source_table.get(eid, "recipes")
        ids_by_table[table].append(eid)

    batch_size = 50
    all_recipe_rows: list[dict] = []
    for table_name, table_ids in ids_by_table.items():
        for i in range(0, len(table_ids), batch_size):
            batch_ids = table_ids[i: i + batch_size]
            try:
                rows = await _fetch_recipes_by_ids(batch_ids, table_name=table_name)
                all_recipe_rows.extend(rows)
            except Exception as exc:
                logger.error(
                    "Failed to fetch recipe batch from %s: %s",
                    table_name, exc,
                )

    # Build recipe_id → row lookup
    recipe_lookup: dict[str, dict] = {}
    for row in all_recipe_rows:
        rid = str(row.get("recipe_id") or "")
        if rid:
            recipe_lookup[rid] = row

    # Step 6: Apply hard filters and assemble results
    results: list[dict] = []
    for sim, entity_id in top_candidates:
        if len(results) >= top_k:
            break

        row = recipe_lookup.get(entity_id)
        if row is None:
            logger.debug("No recipe found for entity_id=%s", entity_id)
            continue

        # Parse recipe data
        recipe_data = row.get("data") or {}
        if isinstance(recipe_data, str):
            try:
                recipe_data = json.loads(recipe_data)
            except json.JSONDecodeError:
                logger.debug("Failed to parse recipe data JSON for entity_id=%s", entity_id)
                continue

        # Apply hard filters
        passes, reason = _passes_hard_filters(recipe_data, retrieval_context.hard_filters)
        if not passes:
            logger.debug("Recipe %s filtered out: %s", entity_id, reason)
            continue

        # Augment with retrieval metadata
        recipe_data["_similarity"] = sim
        recipe_data["_entity_id"] = entity_id
        recipe_data["_source"] = row.get("source", "unknown")
        recipe_data["_source_tier"] = row.get("source_tier", 0)

        results.append(recipe_data)

    logger.info(
        "Stage 3 complete: %d recipes returned (of %d candidates, %d total embeddings)",
        len(results),
        len(top_candidates),
        len(all_embeddings),
    )

    return results
