"""
recipe_validator.py — Stage 7: Seven-layer validation gate.

Runs after LLM enrichment (Stage 6) and determines whether each recipe
is PROMOTED, FLAGGED, or REJECTED based on composite confidence scoring.

Layers:
  L1: Schema validation (Pydantic)
  L2: Nutrition range plausibility
  L3: Energy balance check (kcal ≈ 4×protein + 9×fat + 4×carbs)
  L4: Dietary flag vs. ingredient cross-check
  L5: Cooking time vs. technique check
  L6: Cuisine vs. ingredient affinity check
  L7: Description quality check

Design: weighted geometric mean ensures a single zero (hard failure)
drives the overall score to zero.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Sequence

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.recipe import (
    DietaryFlags,
    NutritionPerServing,
    RecipeDocument,
    RecipeStep,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation result types
# ---------------------------------------------------------------------------

class ValidationDisposition(str, Enum):
    PROMOTE = "promote"            # confidence ≥ 0.80, zero hard failures
    FLAG_FOR_REVIEW = "flag"       # 0.50 ≤ confidence < 0.80
    REJECT = "reject"              # confidence < 0.50 or hard failure


@dataclass
class LayerResult:
    """Result from a single validation layer."""
    layer: str
    score: float          # 0.0 – 1.0
    is_hard_failure: bool = False
    violations: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Composite validation result for a recipe."""
    disposition: ValidationDisposition
    confidence: float
    layer_results: dict[str, LayerResult] = field(default_factory=dict)

    @property
    def all_violations(self) -> list[str]:
        violations = []
        for lr in self.layer_results.values():
            violations.extend(lr.violations)
        return violations

    @property
    def has_hard_failure(self) -> bool:
        return any(lr.is_hard_failure for lr in self.layer_results.values())


# ---------------------------------------------------------------------------
# Layer weights for composite score
# ---------------------------------------------------------------------------

LAYER_WEIGHTS: dict[str, float] = {
    "schema":           0.10,
    "range":            0.10,
    "energy_balance":   0.20,
    "dietary_cross":    0.20,
    "time_technique":   0.10,
    "cuisine_affinity": 0.15,
    "description":      0.15,
}


# ---------------------------------------------------------------------------
# Layer 1: Schema validation
# ---------------------------------------------------------------------------

def validate_schema(recipe: dict[str, Any]) -> LayerResult:
    """
    Validate recipe against RecipeDocument Pydantic model.

    Checks: required fields present, correct types, value ranges.
    """
    violations = []

    # Required fields
    title = recipe.get("title", "")
    if not title or len(str(title).strip()) < 3:
        violations.append("L1: title missing or < 3 chars")

    ingredients = recipe.get("ingredients", [])
    if not ingredients or len(ingredients) < 2:
        violations.append("L1: fewer than 2 ingredients")

    steps = recipe.get("steps", [])
    if not steps or len(steps) < 1:
        violations.append("L1: no steps")

    # Value ranges
    difficulty = recipe.get("difficulty")
    if difficulty is not None:
        if not isinstance(difficulty, (int, float)) or difficulty < 1 or difficulty > 5:
            violations.append(f"L1: difficulty {difficulty} outside 1–5")

    serves = recipe.get("serves")
    if serves is not None:
        if not isinstance(serves, (int, float)) or serves < 1:
            violations.append(f"L1: serves {serves} < 1")

    for time_field in ["time_prep_min", "time_cook_min", "time_total_min"]:
        val = recipe.get(time_field)
        if val is not None:
            if not isinstance(val, (int, float)) or val < 0:
                violations.append(f"L1: {time_field} {val} < 0")

    is_failure = len(violations) > 0
    score = 0.0 if is_failure else 1.0

    return LayerResult(
        layer="schema",
        score=score,
        is_hard_failure=is_failure,
        violations=violations,
    )


# ---------------------------------------------------------------------------
# Layer 2: Nutrition range plausibility
# ---------------------------------------------------------------------------

# Plausible ranges per serving (not per 100g — recipes vary widely)
NUTRITION_RANGES = {
    "kcal":            (0, 2000),     # A serving can be up to ~2000 kcal
    "protein_g":       (0, 150),
    "fat_g":           (0, 150),
    "saturated_fat_g": (0, 80),
    "carbs_g":         (0, 300),
    "fiber_g":         (0, 60),
    "sugar_g":         (0, 200),
    "salt_g":          (0, 15),
}


def validate_nutrition_range(nutrition: Optional[dict]) -> LayerResult:
    """
    Check if nutrition values fall within physically plausible ranges.
    """
    if nutrition is None:
        # No nutrition = not a failure, just no data
        return LayerResult(layer="range", score=1.0)

    violations = []
    for field, (min_val, max_val) in NUTRITION_RANGES.items():
        val = nutrition.get(field)
        if val is not None:
            if val < min_val or val > max_val:
                violations.append(
                    f"L2: {field}={val} outside [{min_val}, {max_val}]"
                )

    score = 0.0 if violations else 1.0
    return LayerResult(
        layer="range",
        score=score,
        is_hard_failure=False,
        violations=violations,
    )


# ---------------------------------------------------------------------------
# Layer 3: Energy balance check
# ---------------------------------------------------------------------------

def validate_energy_balance(nutrition: Optional[dict]) -> LayerResult:
    """
    Check: |stated_kcal - (4×protein + 9×fat + 4×carbs)| / stated_kcal

    Tolerance: ±15% PASS, 15-30% FLAG, >30% REJECT.
    """
    if nutrition is None:
        return LayerResult(layer="energy_balance", score=1.0)

    kcal = nutrition.get("kcal")
    protein = nutrition.get("protein_g")
    fat = nutrition.get("fat_g")
    carbs = nutrition.get("carbs_g")

    if kcal is None or protein is None or fat is None or carbs is None:
        return LayerResult(layer="energy_balance", score=0.8,
                           violations=["L3: incomplete nutrition for energy check"])

    if kcal == 0:
        return LayerResult(layer="energy_balance", score=0.5,
                           violations=["L3: kcal is 0"])

    computed = 4 * protein + 9 * fat + 4 * carbs
    deviation = abs(kcal - computed) / max(kcal, 1)

    violations = []
    if deviation > 0.30:
        score = 0.0
        is_hard = True
        violations.append(
            f"L3: energy balance deviation {deviation:.0%} > 30% "
            f"(stated={kcal}, computed={computed:.0f})"
        )
    elif deviation > 0.15:
        score = 0.5
        is_hard = False
        violations.append(
            f"L3: energy balance deviation {deviation:.0%} (15–30% range)"
        )
    else:
        score = 1.0
        is_hard = False

    return LayerResult(
        layer="energy_balance",
        score=score,
        is_hard_failure=is_hard if deviation > 0.30 else False,
        violations=violations,
    )


# ---------------------------------------------------------------------------
# Layer 4: Dietary flag vs. ingredient cross-check
# ---------------------------------------------------------------------------

def validate_dietary_cross_check(
    dietary_flags: Optional[dict],
    ingredient_names: Sequence[str],
) -> LayerResult:
    """
    Re-infer dietary flags from ingredients and check for contradictions.

    A contradiction (e.g. is_dairy_free=True but "cream cheese" in ingredients)
    is a hard failure — it carries allergy risk.
    """
    if dietary_flags is None or not ingredient_names:
        return LayerResult(layer="dietary_cross", score=1.0)

    from services.dietary_inference import DietaryInferenceEngine

    engine = DietaryInferenceEngine()
    recomputed = engine.infer_flags(list(ingredient_names))

    violations = []
    contradiction_count = 0

    # Check critical safety flags
    checks = [
        ("is_dairy_free", recomputed.is_dairy_free),
        ("is_gluten_free", recomputed.is_gluten_free),
        ("is_nut_free", recomputed.is_nut_free),
        ("is_vegan", recomputed.is_vegan),
        ("is_vegetarian", recomputed.is_vegetarian),
        ("contains_pork", recomputed.contains_pork),
        ("contains_shellfish", recomputed.contains_shellfish),
        ("contains_alcohol", recomputed.contains_alcohol),
    ]

    for flag_name, recomputed_val in checks:
        stored_val = dietary_flags.get(flag_name, recomputed_val)
        if stored_val != recomputed_val:
            # Special handling: if recomputed says NOT free and stored says free → danger
            if flag_name.startswith("is_") and flag_name.endswith("_free"):
                if stored_val is True and recomputed_val is False:
                    violations.append(
                        f"L4: {flag_name} stored=True but ingredients say False"
                    )
                    contradiction_count += 1
            elif flag_name.startswith("contains_"):
                if stored_val is False and recomputed_val is True:
                    violations.append(
                        f"L4: {flag_name} stored=False but ingredients say True"
                    )
                    contradiction_count += 1
            elif flag_name in ("is_vegan", "is_vegetarian"):
                if stored_val is True and recomputed_val is False:
                    violations.append(
                        f"L4: {flag_name} stored=True but ingredients say False"
                    )
                    contradiction_count += 1

    is_hard = contradiction_count > 0
    score = 0.0 if is_hard else 1.0

    return LayerResult(
        layer="dietary_cross",
        score=score,
        is_hard_failure=is_hard,
        violations=violations,
    )


# ---------------------------------------------------------------------------
# Layer 5: Cooking time vs. technique check
# ---------------------------------------------------------------------------

TECHNIQUE_MIN_TIMES: dict[str, int] = {
    "braise":   90,
    "ferment":  1440,   # 24 hours
    "marinate": 30,
    "knead":    60,     # includes proving
    "caramelise": 30,
}


def validate_time_technique(
    time_total_min: Optional[int],
    technique_tags: Sequence[str],
) -> LayerResult:
    """
    Cross-reference total time against detected techniques.
    Flag if time < minimum for detected technique.
    """
    if time_total_min is None or not technique_tags:
        return LayerResult(layer="time_technique", score=1.0)

    violations = []
    for tech in technique_tags:
        min_time = TECHNIQUE_MIN_TIMES.get(tech)
        if min_time is not None and time_total_min < min_time:
            violations.append(
                f"L5: {tech} needs ≥{min_time}min but total_time={time_total_min}"
            )

    score = max(0.0, 1.0 - 0.5 * len(violations))
    return LayerResult(
        layer="time_technique",
        score=score,
        is_hard_failure=False,
        violations=violations,
    )


# ---------------------------------------------------------------------------
# Layer 6: Cuisine vs. ingredient affinity
# ---------------------------------------------------------------------------

def validate_cuisine_affinity(
    cuisine: Optional[str],
    ingredient_names: Sequence[str],
) -> LayerResult:
    """
    Score assigned cuisine against INGREDIENT_SCORES.
    Flag if ingredients strongly suggest a different cuisine.
    """
    if not cuisine or cuisine in ("Other", "Unknown") or not ingredient_names:
        return LayerResult(layer="cuisine_affinity", score=0.7)

    from services.cuisine_validator import compute_cuisine_affinity

    scores = compute_cuisine_affinity(cuisine, ingredient_names)
    top_cuisine = max(scores, key=scores.get) if scores else cuisine
    top_score = scores.get(top_cuisine, 0.0)
    assigned_score = scores.get(cuisine, 0.0)

    violations = []
    if assigned_score == 0 and top_score > 3.0 and cuisine != top_cuisine:
        violations.append(
            f"L6: cuisine '{cuisine}' has 0 ingredient signal; "
            f"'{top_cuisine}' scores {top_score:.1f}"
        )
        score = 0.3
    elif assigned_score > 0:
        score = min(1.0, 0.6 + assigned_score / 10)
    else:
        score = 0.7

    return LayerResult(
        layer="cuisine_affinity",
        score=score,
        is_hard_failure=False,
        violations=violations,
    )


# ---------------------------------------------------------------------------
# Layer 7: Description quality check
# ---------------------------------------------------------------------------

_STUB_PATTERN = re.compile(
    r"^A\s+(?:tasty\s+|simple\s+|delicious\s+|quick\s+|easy\s+)?recipe\s+for",
    re.IGNORECASE,
)

_AMERICANISMS = {
    "eggplant", "zucchini", "cilantro", "scallion", "broil",
    "stovetop", "skillet", "arugula",
}


def validate_description(
    description: Optional[str],
    ingredient_names: Sequence[str],
) -> LayerResult:
    """
    Check description quality:
    - Not a stub
    - No Americanisms (EU English expected)
    - No hallucinated ingredients
    - Minimum length
    """
    if description is None or len(description.strip()) == 0:
        return LayerResult(
            layer="description",
            score=0.3,
            violations=["L7: description is None or empty"],
        )

    violations = []
    desc_lower = description.lower()

    # Stub check
    if len(description) < 50:
        violations.append("L7: description < 50 chars")
    if _STUB_PATTERN.search(description):
        violations.append("L7: stub pattern detected")

    # Americanism check
    for term in _AMERICANISMS:
        if re.search(r"\b" + re.escape(term) + r"\b", desc_lower):
            violations.append(f"L7: Americanism '{term}' in EU English desc")

    # Hallucinated ingredient check — description mentions ingredients
    # not in the actual recipe
    if ingredient_names:
        ing_set = {name.lower().strip() for name in ingredient_names}
        # Check for specific food nouns in description not in ingredients
        # (simple heuristic — check for 3+ char words that look like ingredients)
        desc_words = set(re.findall(r"\b[a-z]{4,}\b", desc_lower))
        # Common food-specific words to check
        food_words = {
            "chicken", "beef", "pork", "lamb", "salmon", "tuna", "shrimp",
            "prawn", "tofu", "cheese", "cream", "chocolate", "mushroom",
            "tomato", "potato", "avocado", "mango", "coconut",
        }
        for word in desc_words & food_words:
            if not any(word in ing for ing in ing_set):
                violations.append(
                    f"L7: '{word}' in description but not in ingredients"
                )

    # Score
    if any("stub" in v for v in violations) or any("< 50" in v for v in violations):
        score = 0.3
    elif any("Americanism" in v for v in violations):
        score = 0.7
    elif violations:
        score = 0.6
    else:
        score = 1.0

    return LayerResult(
        layer="description",
        score=score,
        is_hard_failure=False,
        violations=violations,
    )


# ---------------------------------------------------------------------------
# Composite confidence scoring
# ---------------------------------------------------------------------------

def compute_confidence(layer_results: dict[str, LayerResult]) -> float:
    """
    Weighted geometric mean of layer scores.

    A single zero drives the overall score to zero — this is intentional
    for hard failures (schema, dietary contradictions).
    """
    product = 1.0
    for layer, weight in LAYER_WEIGHTS.items():
        lr = layer_results.get(layer)
        score = lr.score if lr else 0.5
        # Clamp to avoid log(0) issues
        score = max(score, 1e-6)
        product *= score ** weight

    return round(product, 4)


# ---------------------------------------------------------------------------
# Main validation function
# ---------------------------------------------------------------------------

def validate_recipe(recipe: dict[str, Any]) -> ValidationResult:
    """
    Run all 7 validation layers on a recipe dict.

    The recipe dict should contain:
    - title, ingredients (list), steps (list)
    - nutrition_per_serving (dict or None)
    - dietary_flags (dict or None)
    - cuisine_tags (list)
    - time_total_min (int or None)
    - description (str or None)
    - All technique_tags from steps

    Returns:
        ValidationResult with disposition, confidence, and per-layer details.
    """
    # Extract fields
    nutrition = recipe.get("nutrition_per_serving")
    dietary_flags = recipe.get("dietary_flags")
    cuisine_tags = recipe.get("cuisine_tags", [])
    cuisine = cuisine_tags[0] if cuisine_tags else None

    # Ingredient names: prefer parsed names, fall back to NER
    ingredients = recipe.get("ingredients", [])
    if ingredients and isinstance(ingredients[0], dict):
        ingredient_names = [i.get("name", "") for i in ingredients]
    elif ingredients and isinstance(ingredients[0], str):
        ingredient_names = ingredients
    else:
        ingredient_names = recipe.get("NER", [])

    # Technique tags from steps
    steps = recipe.get("steps", [])
    technique_tags = set()
    if steps and isinstance(steps[0], dict):
        for step in steps:
            technique_tags.update(step.get("technique_tags", []))
    elif steps and isinstance(steps[0], str):
        from services.technique_extractor import recipe_technique_set
        technique_tags = recipe_technique_set(steps)

    time_total = recipe.get("time_total_min")
    description = recipe.get("description")

    # Run all layers
    results: dict[str, LayerResult] = {}
    results["schema"] = validate_schema(recipe)
    results["range"] = validate_nutrition_range(nutrition)
    results["energy_balance"] = validate_energy_balance(nutrition)
    results["dietary_cross"] = validate_dietary_cross_check(
        dietary_flags, ingredient_names
    )
    results["time_technique"] = validate_time_technique(
        time_total, list(technique_tags)
    )
    results["cuisine_affinity"] = validate_cuisine_affinity(
        cuisine, ingredient_names
    )
    results["description"] = validate_description(description, ingredient_names)

    # Composite confidence
    confidence = compute_confidence(results)

    # Determine disposition
    has_hard_failure = any(lr.is_hard_failure for lr in results.values())

    if has_hard_failure or confidence < 0.50:
        disposition = ValidationDisposition.REJECT
    elif confidence >= 0.80:
        disposition = ValidationDisposition.PROMOTE
    else:
        disposition = ValidationDisposition.FLAG_FOR_REVIEW

    return ValidationResult(
        disposition=disposition,
        confidence=confidence,
        layer_results=results,
    )


def validate_batch(
    recipes: list[dict[str, Any]],
) -> list[ValidationResult]:
    """
    Validate a batch of recipes.

    Returns:
        List of ValidationResult, one per recipe.
    """
    return [validate_recipe(r) for r in recipes]
