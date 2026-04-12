"""
cuisine_validator.py — Cuisine classification validation layer.

Cross-validates assigned cuisine tags against ingredient-cuisine affinity
scores from the existing INGREDIENT_SCORES dict in cuisine_classifier.py.

Catches "miso in Italian recipe" class of misattributions where LLMs
default to generic cuisine assignments that contradict ingredient signals.
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger(__name__)

# Lazy import to avoid pulling in LLM dependencies
_INGREDIENT_SCORES: dict | None = None


def _get_ingredient_scores() -> dict:
    global _INGREDIENT_SCORES
    if _INGREDIENT_SCORES is None:
        try:
            from services.cuisine_classifier import INGREDIENT_SCORES
            _INGREDIENT_SCORES = INGREDIENT_SCORES
        except ImportError:
            logger.warning("Could not import INGREDIENT_SCORES from cuisine_classifier")
            _INGREDIENT_SCORES = {}
    return _INGREDIENT_SCORES


def compute_cuisine_affinity(
    cuisine: str,
    ner_ingredients: Sequence[str],
) -> dict[str, float]:
    """
    Score all cuisines against the given ingredient list.

    Returns:
        Dict mapping cuisine name → affinity score.
    """
    scores: dict[str, float] = {}
    for cuisine_name, ingredient_weights in _get_ingredient_scores().items():
        total = 0.0
        for ing, weight in ingredient_weights.items():
            if any(ing.lower() in n.lower() for n in ner_ingredients):
                total += weight
        scores[cuisine_name] = total
    return scores


def validate_cuisine_attribution(
    cuisine: str,
    ner_ingredients: Sequence[str],
    override_threshold: float = 3.0,
) -> tuple[str, float]:
    """
    Cross-validate a cuisine assignment against ingredient signals.

    Logic:
    - If the assigned cuisine has zero ingredient signal but another
      cuisine scores > override_threshold, override with the
      ingredient-derived cuisine.
    - If the assigned cuisine has positive ingredient signal,
      compute confidence from its score.
    - Otherwise, return the assigned cuisine with low confidence.

    Args:
        cuisine: The cuisine tag to validate.
        ner_ingredients: List of NER ingredient names.
        override_threshold: Minimum score to trigger an override.

    Returns:
        Tuple of (validated_cuisine, confidence_score).
    """
    if not ner_ingredients:
        return cuisine, 0.5

    scores = compute_cuisine_affinity(cuisine, ner_ingredients)

    top_cuisine = max(scores, key=scores.get) if scores else cuisine
    top_score = scores.get(top_cuisine, 0.0)
    assigned_score = scores.get(cuisine, 0.0)

    # Case 1: Assigned cuisine has zero ingredient signal,
    # but another cuisine scores strongly → override
    if (
        assigned_score == 0
        and top_score > override_threshold
        and cuisine != top_cuisine
    ):
        logger.info(
            "Cuisine override: '%s' (score=0) → '%s' (score=%.1f) "
            "based on ingredient affinity",
            cuisine, top_cuisine, top_score,
        )
        return top_cuisine, 0.7

    # Case 2: Assigned cuisine has positive ingredient signal → confidence
    if assigned_score > 0:
        confidence = min(0.95, 0.6 + assigned_score / 10)
        return cuisine, confidence

    # Case 3: No signal either way → low confidence, keep original
    return cuisine, 0.5


def batch_validate_cuisines(
    recipes: list[dict],
    cuisine_key: str = "cuisine_tags",
    ner_key: str = "NER",
) -> list[tuple[str, float]]:
    """
    Validate cuisine tags for a batch of recipes.

    Args:
        recipes: List of recipe dicts with cuisine_tags and NER fields.
        cuisine_key: Key for cuisine tags in each recipe dict.
        ner_key: Key for NER ingredient list in each recipe dict.

    Returns:
        List of (validated_cuisine, confidence) tuples.
    """
    results = []
    for recipe in recipes:
        cuisine_tags = recipe.get(cuisine_key, [])
        cuisine = cuisine_tags[0] if cuisine_tags else "Other"
        ner = recipe.get(ner_key, [])
        validated, confidence = validate_cuisine_attribution(cuisine, ner)
        results.append((validated, confidence))
    return results
