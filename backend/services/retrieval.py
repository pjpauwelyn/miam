"""
Retrieval service — pgvector semantic search + metadata filtering.

Handles Stage 3 (Retrieval) of the miam pipeline:
- Eat In: pgvector cosine similarity on embedded recipe corpus
- Eat Out: FSQOSAdapter.search() on local Amsterdam restaurant JSON
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from services.embeddings import generate_embedding

logger = logging.getLogger(__name__)

# Default retrieval parameters
DEFAULT_TOP_K = 20


async def search_recipes(
    query_embedding: list[float],
    pool,  # asyncpg pool
    *,
    top_k: int = DEFAULT_TOP_K,
    dietary_filters: dict[str, bool] | None = None,
    max_time_min: int | None = None,
) -> list[dict[str, Any]]:
    """
    Semantic search over recipe embeddings using pgvector cosine similarity.

    Pre-filters by dietary hard stops and time constraint before ranking.

    Args:
        query_embedding: 1024-dim query vector.
        pool: asyncpg connection pool.
        top_k: Number of candidates to return (default 20).
        dietary_filters: Dict of dietary flag name -> required value.
        max_time_min: Max total cooking time filter.

    Returns:
        List of recipe dicts with cosine similarity scores.
    """
    # Build the base query
    query = """
        SELECT 
            e.entity_id,
            r.data,
            1 - (e.embedding <=> $1::vector) AS similarity
        FROM embeddings e
        JOIN recipes r ON r.recipe_id = e.entity_id
        WHERE e.entity_type = 'recipe'
    """
    params: list[Any] = [str(query_embedding)]
    param_idx = 2

    # Add dietary hard-stop filters
    if dietary_filters:
        for flag_name, required_value in dietary_filters.items():
            query += f" AND (r.data->'dietary_flags'->>'{flag_name}')::boolean = ${param_idx}"
            params.append(required_value)
            param_idx += 1

    # Add time constraint filter
    if max_time_min is not None:
        query += f" AND (r.data->>'time_total_min')::int <= ${param_idx}"
        params.append(max_time_min)
        param_idx += 1

    query += f" ORDER BY e.embedding <=> $1::vector LIMIT ${param_idx}"
    params.append(top_k)

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    results = []
    for row in rows:
        data = row["data"]
        if isinstance(data, str):
            import json
            data = json.loads(data)
        data["_similarity"] = float(row["similarity"])
        data["_entity_id"] = str(row["entity_id"])
        results.append(data)

    logger.debug("Recipe search returned %d results (top_k=%d)", len(results), top_k)
    return results


async def search_recipes_by_text(
    query_text: str,
    pool,
    *,
    top_k: int = DEFAULT_TOP_K,
    dietary_filters: dict[str, bool] | None = None,
    max_time_min: int | None = None,
) -> list[dict[str, Any]]:
    """
    Convenience wrapper: embed the query text, then search.
    """
    embedding = await generate_embedding(query_text)
    return await search_recipes(
        embedding,
        pool,
        top_k=top_k,
        dietary_filters=dietary_filters,
        max_time_min=max_time_min,
    )


async def get_embedding_count(pool, entity_type: str = "recipe") -> int:
    """Get the count of embeddings for a given entity type."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) as count FROM embeddings WHERE entity_type = $1",
            entity_type,
        )
        return row["count"] if row else 0
