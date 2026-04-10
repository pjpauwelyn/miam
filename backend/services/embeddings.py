"""
Embedding generation service via Mistral Embeddings API.

Uses mistral-embed model for generating 1024-dimensional vectors
for recipes, restaurants, and user profiles.
"""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import Sequence

from mistralai import Mistral

from config import settings

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "mistral-embed"
EMBEDDING_DIMENSION = 1024
BATCH_SIZE = 25  # Mistral allows up to 32 texts per batch


@lru_cache(maxsize=1)
def _get_client() -> Mistral:
    return Mistral(api_key=settings.MISTRAL_API_KEY)


async def generate_embedding(text: str) -> list[float]:
    """Generate a single embedding vector for the given text."""
    result = await generate_embeddings([text])
    return result[0]


async def generate_embeddings(texts: Sequence[str]) -> list[list[float]]:
    """
    Generate embedding vectors for multiple texts.
    Handles batching automatically.

    Returns:
        List of 1024-dimensional float vectors, one per input text.
    """
    client = _get_client()
    all_embeddings: list[list[float]] = []
    loop = asyncio.get_event_loop()

    for i in range(0, len(texts), BATCH_SIZE):
        batch = list(texts[i:i + BATCH_SIZE])
        try:
            def _sync_embed(b: list[str] = batch) -> list[list[float]]:
                response = client.embeddings.create(
                    model=EMBEDDING_MODEL,
                    inputs=b,
                )
                return [item.embedding for item in response.data]

            batch_embeddings = await asyncio.wait_for(
                loop.run_in_executor(None, _sync_embed),
                timeout=30.0,
            )
            all_embeddings.extend(batch_embeddings)

            logger.debug(
                "Embedded batch %d–%d of %d texts",
                i, min(i + BATCH_SIZE, len(texts)), len(texts),
            )

        except asyncio.TimeoutError:
            logger.error("Embedding request timed out for batch starting at index %d", i)
            raise
        except Exception:
            logger.exception("Embedding request failed for batch starting at index %d", i)
            raise

    return all_embeddings


def build_recipe_embedding_text(recipe: dict) -> str:
    """
    Build the embedding text for a recipe document.
    Concatenates semantically relevant fields — excludes amounts and prep notes.
    """
    parts = [
        recipe.get("title_en", recipe.get("title", "")),
        recipe.get("description", ""),
        " ".join(
            i.get("name", "") if isinstance(i, dict) else str(i)
            for i in recipe.get("ingredients", [])
        ),
        " ".join(recipe.get("flavor_tags", [])),
        " ".join(recipe.get("texture_tags", [])),
        " ".join(recipe.get("dietary_tags", [])),
        " ".join(recipe.get("occasion_tags", [])),
        " ".join(recipe.get("season_tags", [])),
        " ".join(recipe.get("cuisine_tags", [])),
    ]
    return " ".join(filter(None, parts))


def build_restaurant_embedding_text(restaurant: dict) -> str:
    """Build the embedding text for a restaurant document."""
    cuisine = restaurant.get("cuisine_tags", {})
    if isinstance(cuisine, dict):
        cuisine_parts = [cuisine.get("primary", "")] + cuisine.get("secondary", [])
    elif isinstance(cuisine, list):
        cuisine_parts = cuisine
    else:
        cuisine_parts = []

    parts = [
        restaurant.get("name", ""),
        restaurant.get("neighborhood", ""),
        " ".join(cuisine_parts),
        " ".join(restaurant.get("vibe_tags", [])),
        restaurant.get("menu_summary", "") or "",
        restaurant.get("review_summary", "") or "",
        " ".join(restaurant.get("specialties", [])),
    ]
    return " ".join(filter(None, parts))
