"""
CuisineClassifier — batch cuisine classification using Mistral Small.

Classifies recipes into one of 25 controlled cuisine tags based on
title + ingredient NER list. Uses the LLM router for all API calls.

Batch mode: groups up to 20 recipes per LLM call to minimise API cost.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Sequence

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.llm_router import LLMOperation, call_llm_json

logger = logging.getLogger(__name__)

# Controlled vocabulary of 25 cuisines — must be used in all classification outputs
CUISINE_VOCABULARY: list[str] = [
    "Italian", "French", "Spanish", "Greek", "Moroccan",
    "Lebanese", "Turkish", "Indian", "Chinese", "Japanese",
    "Korean", "Thai", "Vietnamese", "Mexican", "Peruvian",
    "American", "British", "German", "Dutch", "Scandinavian",
    "Middle Eastern", "African", "Caribbean", "Fusion", "Other",
]

# Maximum recipes per batch LLM call
_BATCH_SIZE = 20

# System prompt for classification
_SYSTEM_PROMPT = f"""You are a culinary cuisine classifier. Given a list of recipes (each with a title and ingredient list), classify each recipe into exactly ONE primary cuisine from this controlled vocabulary:

{json.dumps(CUISINE_VOCABULARY)}

Rules:
- Return a JSON array of objects, one per recipe, in the same order as the input.
- Each object must have: {{"index": <int>, "cuisine": "<string from vocabulary>"}}
- Use "Fusion" for recipes that clearly blend two or more cuisines.
- Use "Other" only if no cuisine in the vocabulary fits.
- Base your classification on both the recipe title and the ingredient combination.
- Consider ingredient patterns: e.g. soy sauce + ginger + rice = likely East Asian; cumin + coriander + chickpea = likely Middle Eastern/Indian.
- If the title explicitly names a cuisine (e.g. "Thai Green Curry"), honour it.
- Return ONLY the JSON array, no markdown, no explanation."""


class CuisineClassifier:
    """
    Batch cuisine classifier using Mistral Small via the LLM router.

    Usage:
        classifier = CuisineClassifier()
        results = await classifier.classify_batch(recipes)
        # results = [{"index": 0, "cuisine": "Italian"}, ...]
    """

    async def classify_batch(
        self,
        recipes: Sequence[dict],
    ) -> list[dict]:
        """
        Classify a batch of recipes into cuisine tags.

        Args:
            recipes: List of dicts with "title" and "NER" (ingredient names) keys.

        Returns:
            List of dicts with "index" and "cuisine" keys, in input order.
        """
        all_results: list[dict] = []

        for batch_start in range(0, len(recipes), _BATCH_SIZE):
            batch = recipes[batch_start:batch_start + _BATCH_SIZE]
            batch_results = await self._classify_single_batch(batch, batch_start)
            all_results.extend(batch_results)

        return all_results

    async def _classify_single_batch(
        self,
        batch: Sequence[dict],
        offset: int,
    ) -> list[dict]:
        """Classify a single batch (≤20 recipes) via one LLM call."""
        # Build user prompt with recipe data
        recipe_lines: list[str] = []
        for i, recipe in enumerate(batch):
            title = recipe.get("title", "Untitled")
            ner = recipe.get("NER", [])
            if isinstance(ner, str):
                ner = [ner]
            ingredients_str = ", ".join(ner[:15])  # Limit to 15 ingredients to save tokens
            recipe_lines.append(f"{i}. \"{title}\" — Ingredients: {ingredients_str}")

        user_prompt = (
            f"Classify these {len(batch)} recipes:\n\n"
            + "\n".join(recipe_lines)
        )

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            result = await call_llm_json(
                LLMOperation.CUISINE_CLASSIFICATION,
                messages,
                temperature=0,
                max_tokens=1500,
            )

            # Validate and normalise
            if isinstance(result, list):
                return self._validate_results(result, len(batch), offset)
            elif isinstance(result, dict) and "classifications" in result:
                return self._validate_results(result["classifications"], len(batch), offset)
            else:
                logger.warning("Unexpected LLM response format: %s", type(result))
                return self._fallback_results(len(batch), offset)

        except Exception as e:
            logger.error("Cuisine classification failed for batch at offset %d: %s", offset, e)
            return self._fallback_results(len(batch), offset)

    def _validate_results(
        self,
        results: list,
        expected_count: int,
        offset: int,
    ) -> list[dict]:
        """Validate and normalise LLM classification results."""
        validated: list[dict] = []

        for i in range(expected_count):
            # Try to find the result for this index
            cuisine = "Other"
            for r in results:
                if isinstance(r, dict) and r.get("index") == i:
                    raw_cuisine = r.get("cuisine", "Other")
                    # Validate against vocabulary
                    if raw_cuisine in CUISINE_VOCABULARY:
                        cuisine = raw_cuisine
                    else:
                        # Try case-insensitive match
                        for vc in CUISINE_VOCABULARY:
                            if vc.lower() == raw_cuisine.lower():
                                cuisine = vc
                                break
                    break

            validated.append({
                "index": offset + i,
                "cuisine": cuisine,
            })

        return validated

    @staticmethod
    def _fallback_results(count: int, offset: int) -> list[dict]:
        """Return 'Other' for all recipes in a failed batch."""
        return [{"index": offset + i, "cuisine": "Other"} for i in range(count)]


async def classify_recipes(recipes: Sequence[dict]) -> list[dict]:
    """Convenience function: classify a list of recipes."""
    classifier = CuisineClassifier()
    return await classifier.classify_batch(recipes)
