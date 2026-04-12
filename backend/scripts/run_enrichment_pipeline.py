#!/usr/bin/env python3
"""
run_enrichment_pipeline.py — Master orchestrator for the MIAM enrichment pipeline.

Executes all stages in sequence on recipes from the Supabase recipes_open table:

  Stage 0: Quality gate (SQL selection — run separately via stratified_selection.sql)
  Stage 1: Ingredient parsing
  Stage 2: Deterministic tagging (course, dietary, technique)
  Stage 3: Nutrition lookup (CIQUAL → USDA → OFF)
  Stage 4: Cuisine classification + ingredient affinity validation
  Stage 5: Deterministic derivation (difficulty, season, flavor, texture, categories, allergens)
  Stage 6: Narrow LLM enrichment (description, region, tips, cultural, pairings, storage)
  Stage 7: Validation gate (7-layer confidence scoring)

Each stage is idempotent: progress is tracked via enrichment_status and recipes
at a later stage are skipped. The pipeline can be resumed after interruption.

Usage:
    cd backend && python scripts/run_enrichment_pipeline.py [--stage N] [--batch-size N] [--limit N]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BACKEND_DIR)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("pipeline")

# ---------------------------------------------------------------------------
# Stage status constants (match EnrichmentStatus enum)
# ---------------------------------------------------------------------------

STATUS_RAW = "raw"
STATUS_PARSED = "parsed"
STATUS_DETERMINISTIC = "deterministic_enriched"
STATUS_LLM = "llm_enriched"
STATUS_VALIDATED = "validated"
STATUS_FLAGGED = "flagged"
STATUS_REJECTED = "rejected"

# Ordered stages — a recipe at status N has completed all stages ≤ N
STATUS_ORDER = [STATUS_RAW, STATUS_PARSED, STATUS_DETERMINISTIC, STATUS_LLM, STATUS_VALIDATED]


# ---------------------------------------------------------------------------
# Stage 1: Ingredient parsing
# ---------------------------------------------------------------------------

def run_stage_1(recipe: dict) -> dict:
    """Parse raw ingredient strings into structured RecipeIngredient objects."""
    from services.ingredient_parser import parse_recipe_ingredients

    raw_ingredients = recipe.get("raw_ingredients_text", [])
    if not raw_ingredients:
        # Fall back to data.ingredients if it's a list of strings
        data = recipe.get("data", {})
        raw_ingredients = data.get("ingredients", [])
        if raw_ingredients and isinstance(raw_ingredients[0], str):
            recipe["raw_ingredients_text"] = raw_ingredients

    ner = recipe.get("NER", recipe.get("data", {}).get("NER", []))

    parsed = parse_recipe_ingredients(raw_ingredients, ner)

    recipe["ingredients"] = [
        {
            "name": p.name,
            "amount": p.amount,
            "unit": p.unit,
            "notes": p.notes,
            "is_optional": p.is_optional,
        }
        for p in parsed
    ]

    # Parse steps
    raw_steps = recipe.get("steps", recipe.get("data", {}).get("directions", []))
    if raw_steps and isinstance(raw_steps[0], str):
        recipe["steps"] = [
            {"step_number": i + 1, "instruction": s, "technique_tags": []}
            for i, s in enumerate(raw_steps)
        ]

    recipe["enrichment_status"] = STATUS_PARSED
    return recipe


# ---------------------------------------------------------------------------
# Stage 2: Deterministic tagging
# ---------------------------------------------------------------------------

def run_stage_2(recipe: dict) -> dict:
    """Run course tagger, dietary inference, and technique extractor."""
    from services.dietary_inference import DietaryInferenceEngine
    from services.technique_extractor import extract_techniques_from_text

    engine = DietaryInferenceEngine()

    # Technique extraction on steps
    steps = recipe.get("steps", [])
    for step in steps:
        if isinstance(step, dict) and "instruction" in step:
            step["technique_tags"] = extract_techniques_from_text(step["instruction"])

    # Dietary flags from ingredient names
    ingredient_names = _get_ingredient_names(recipe)
    flags = engine.infer_flags(ingredient_names)
    recipe["dietary_flags"] = {
        "is_vegan": flags.is_vegan,
        "is_vegetarian": flags.is_vegetarian,
        "is_pescatarian_ok": flags.is_pescatarian_ok,
        "is_dairy_free": flags.is_dairy_free,
        "is_gluten_free": flags.is_gluten_free,
        "is_nut_free": flags.is_nut_free,
        "is_halal_ok": flags.is_halal_ok,
        "contains_pork": flags.contains_pork,
        "contains_shellfish": flags.contains_shellfish,
        "contains_alcohol": flags.contains_alcohol,
        "vegan_if_substituted": flags.vegan_if_substituted,
        "gluten_free_if_substituted": flags.gluten_free_if_substituted,
    }
    recipe["dietary_tags"] = engine.dietary_tags_from_flags(flags)

    recipe["enrichment_status"] = STATUS_DETERMINISTIC
    return recipe


# ---------------------------------------------------------------------------
# Stage 3: Nutrition lookup
# ---------------------------------------------------------------------------

def run_stage_3(recipe: dict) -> dict:
    """Look up nutrition via CIQUAL → USDA → OFF chain."""
    from services.ingredient_parser import estimate_grams, RecipeIngredient
    from services.nutrition_lookup import get_nutrition_lookup

    nl = get_nutrition_lookup()
    ingredient_names = _get_ingredient_names(recipe)
    ingredients = recipe.get("ingredients", [])
    serves = recipe.get("serves") or 4

    total = {"kcal": 0, "protein_g": 0, "fat_g": 0, "saturated_fat_g": 0,
             "carbs_g": 0, "fiber_g": 0, "sugar_g": 0, "salt_g": 0}
    matched = 0
    sources_used = set()

    for i, name in enumerate(ingredient_names):
        result = nl.lookup(name)
        if result:
            matched += 1
            sources_used.add(result.source)

            # Estimate grams for this ingredient
            if i < len(ingredients) and isinstance(ingredients[i], dict):
                ri = RecipeIngredient(
                    name=ingredients[i].get("name", name),
                    amount=ingredients[i].get("amount", 1.0),
                    unit=ingredients[i].get("unit", "piece"),
                )
                grams = estimate_grams(ri)
            else:
                grams = 100  # default assumption

            factor = grams / 100.0
            total["kcal"] += result.kcal * factor
            total["protein_g"] += result.protein_g * factor
            total["fat_g"] += result.fat_g * factor
            total["saturated_fat_g"] += result.saturated_fat_g * factor
            total["carbs_g"] += result.carbs_g * factor
            total["fiber_g"] += result.fiber_g * factor
            total["sugar_g"] += result.sugar_g * factor
            total["salt_g"] += result.salt_g * factor

    if matched > 0 and matched >= len(ingredient_names) * 0.5:
        recipe["nutrition_per_serving"] = {
            "kcal": max(1, int(total["kcal"] / serves)),
            "protein_g": round(total["protein_g"] / serves, 1),
            "fat_g": round(total["fat_g"] / serves, 1),
            "saturated_fat_g": round(total["saturated_fat_g"] / serves, 1),
            "carbs_g": round(total["carbs_g"] / serves, 1),
            "fiber_g": round(total["fiber_g"] / serves, 1),
            "sugar_g": round(total["sugar_g"] / serves, 1),
            "salt_g": round(total["salt_g"] / serves, 2),
        }
        recipe["nutrition_provenance"] = {
            "source": ", ".join(sorted(sources_used)),
            "confidence": 0.85 if "ciqual" in sources_used else 0.7,
            "matched_ratio": matched / max(len(ingredient_names), 1),
        }
    else:
        recipe["nutrition_per_serving"] = None
        recipe["nutrition_provenance"] = None

    return recipe


# ---------------------------------------------------------------------------
# Stage 4: Cuisine classification + validation
# ---------------------------------------------------------------------------

def run_stage_4(recipe: dict) -> dict:
    """Classify cuisine and validate against ingredient affinity."""
    from services.cuisine_classifier import classify_rule_based
    from services.cuisine_validator import validate_cuisine_attribution

    title = recipe.get("title", "")
    ner = _get_ingredient_names(recipe)

    # Rule-based first
    rule_cuisine = classify_rule_based(title, ner)

    if rule_cuisine and rule_cuisine != "Other":
        # Validate against ingredient affinity
        validated, confidence = validate_cuisine_attribution(rule_cuisine, ner)
        recipe["cuisine_tags"] = [validated]
        recipe["cuisine_confidence"] = confidence
        recipe["cuisine_method"] = "rule_based + affinity_validated"
    else:
        # No rule-based match — will need LLM in Stage 6
        # For now, set as Unknown with low confidence
        recipe["cuisine_tags"] = recipe.get("cuisine_tags", ["Unknown"])
        recipe["cuisine_confidence"] = 0.3
        recipe["cuisine_method"] = "pending_llm"

    return recipe


# ---------------------------------------------------------------------------
# Stage 5: Deterministic derivation
# ---------------------------------------------------------------------------

def run_stage_5(recipe: dict) -> dict:
    """Compute difficulty, season, flavor, texture, categories, allergens."""
    from services.deterministic_enrichment import (
        compute_difficulty,
        compute_season_tags,
        compute_flavor_tags,
        categorise_ingredient,
    )
    from services.technique_extractor import (
        recipe_technique_set,
        infer_textures_from_techniques,
        HARD_TECHNIQUES,
    )
    from services.allergen_detector import detect_allergens

    ingredient_names = _get_ingredient_names(recipe)
    ingredients = recipe.get("ingredients", [])

    # Technique set
    steps = recipe.get("steps", [])
    if steps and isinstance(steps[0], dict):
        step_texts = [s.get("instruction", "") for s in steps]
    elif steps and isinstance(steps[0], str):
        step_texts = steps
    else:
        step_texts = []

    techniques = recipe_technique_set(step_texts)

    # Difficulty
    recipe["difficulty"] = compute_difficulty(
        ingredient_count=len(ingredient_names),
        technique_set=techniques,
        total_time_min=recipe.get("time_total_min"),
    )

    # Season tags
    recipe["season_tags"] = compute_season_tags(ingredient_names)

    # Flavor tags (deterministic from FlavorDB)
    recipe["flavor_tags"] = compute_flavor_tags(ingredient_names, max_tags=3)

    # Texture tags (from techniques)
    recipe["texture_tags"] = infer_textures_from_techniques(techniques)

    # Ingredient categories
    for ing in ingredients:
        if isinstance(ing, dict) and "name" in ing:
            cat = categorise_ingredient(ing["name"])
            if cat:
                ing["category"] = cat

    # Allergen warnings
    recipe["allergen_warnings"] = detect_allergens(ingredient_names)

    # Provenance tracking
    recipe["provenance_parts"] = []
    if recipe.get("nutrition_per_serving"):
        np = recipe.get("nutrition_provenance", {})
        recipe["provenance_parts"].append(
            f"Nutrition from {np.get('source', 'lookup')} "
            f"(confidence: {np.get('confidence', 0):.2f})"
        )
    if recipe.get("cuisine_method") == "rule_based + affinity_validated":
        recipe["provenance_parts"].append(
            f"Cuisine from rule-based classifier "
            f"(confidence: {recipe.get('cuisine_confidence', 0):.2f})"
        )
    recipe["provenance_parts"].append("Dietary flags from deterministic inference")
    recipe["provenance_parts"].append("Difficulty from heuristic computation")

    return recipe


# ---------------------------------------------------------------------------
# Stage 6: Narrow LLM enrichment
# ---------------------------------------------------------------------------

async def run_stage_6_batch(recipes: list[dict]) -> list[dict]:
    """Run narrow LLM enrichment on a batch."""
    from scripts.enrich_recipes_narrow import run_narrow_enrichment

    recipes = await run_narrow_enrichment(recipes)

    for recipe in recipes:
        recipe["enrichment_status"] = STATUS_LLM
        # Build provenance summary
        parts = recipe.get("provenance_parts", [])
        if recipe.get("description"):
            parts.append("Description from Mistral Small")
        recipe["provenance_summary"] = ". ".join(parts) + "."

    return recipes


# ---------------------------------------------------------------------------
# Stage 7: Validation gate
# ---------------------------------------------------------------------------

def run_stage_7(recipe: dict) -> dict:
    """Run 7-layer validation and determine disposition."""
    from services.recipe_validator import validate_recipe, ValidationDisposition

    result = validate_recipe(recipe)

    recipe["validation_confidence"] = result.confidence
    recipe["validation_disposition"] = result.disposition.value
    recipe["validation_violations"] = result.all_violations

    if result.disposition == ValidationDisposition.PROMOTE:
        recipe["enrichment_status"] = STATUS_VALIDATED
    elif result.disposition == ValidationDisposition.FLAG_FOR_REVIEW:
        recipe["enrichment_status"] = STATUS_FLAGGED
    else:
        recipe["enrichment_status"] = STATUS_REJECTED
        recipe["promotion_blocked_reason"] = "; ".join(result.all_violations[:5])

    return recipe


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_ingredient_names(recipe: dict) -> list[str]:
    """Extract ingredient names from recipe, handling multiple formats."""
    ingredients = recipe.get("ingredients", [])
    if ingredients and isinstance(ingredients[0], dict):
        return [i.get("name", "") for i in ingredients if i.get("name")]
    elif ingredients and isinstance(ingredients[0], str):
        return ingredients
    return recipe.get("NER", recipe.get("data", {}).get("NER", []))


# ---------------------------------------------------------------------------
# Main pipeline runner
# ---------------------------------------------------------------------------

async def run_pipeline(
    recipes: list[dict],
    start_stage: int = 1,
    end_stage: int = 7,
    skip_llm: bool = False,
) -> list[dict]:
    """
    Run the enrichment pipeline on a list of recipe dicts.

    Args:
        recipes: List of raw recipe dicts.
        start_stage: First stage to run (1–7).
        end_stage: Last stage to run (1–7).
        skip_llm: If True, skip Stage 6 (LLM enrichment).

    Returns:
        Enriched recipe list.
    """
    total = len(recipes)
    logger.info("Pipeline starting: %d recipes, stages %d–%d", total, start_stage, end_stage)

    for i, recipe in enumerate(recipes):
        # Determine current stage from enrichment_status
        status = recipe.get("enrichment_status", STATUS_RAW)

        if start_stage <= 1 and status == STATUS_RAW:
            recipe = run_stage_1(recipe)

        if start_stage <= 2 and STATUS_ORDER.index(recipe.get("enrichment_status", STATUS_RAW)) < STATUS_ORDER.index(STATUS_DETERMINISTIC):
            recipe = run_stage_2(recipe)

        if start_stage <= 3:
            recipe = run_stage_3(recipe)

        if start_stage <= 4:
            recipe = run_stage_4(recipe)

        if start_stage <= 5 and end_stage >= 5:
            recipe = run_stage_5(recipe)

        recipes[i] = recipe

        if (i + 1) % 500 == 0:
            logger.info("Stages 1–5: %d/%d complete", i + 1, total)

    logger.info("Stages 1–5 complete for all %d recipes", total)

    # Stage 6: LLM enrichment (batch)
    if not skip_llm and start_stage <= 6 and end_stage >= 6:
        # Only enrich recipes that haven't been LLM-enriched yet
        needs_llm = [r for r in recipes if r.get("enrichment_status") != STATUS_LLM]
        if needs_llm:
            logger.info("Stage 6: %d recipes need LLM enrichment", len(needs_llm))
            await run_stage_6_batch(needs_llm)
        else:
            logger.info("Stage 6: all recipes already LLM-enriched")

    # Stage 7: Validation
    if start_stage <= 7 and end_stage >= 7:
        promoted = flagged = rejected = 0
        for i, recipe in enumerate(recipes):
            recipe = run_stage_7(recipe)
            recipes[i] = recipe

            disp = recipe.get("validation_disposition", "")
            if disp == "promote":
                promoted += 1
            elif disp == "flag":
                flagged += 1
            else:
                rejected += 1

        logger.info(
            "Stage 7 complete: %d promoted, %d flagged, %d rejected "
            "(total: %d)",
            promoted, flagged, rejected, total,
        )

    return recipes


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="MIAM Enrichment Pipeline")
    parser.add_argument("--input", help="Input JSONL file")
    parser.add_argument("--output", help="Output JSONL file")
    parser.add_argument("--start-stage", type=int, default=1, help="First stage (1–7)")
    parser.add_argument("--end-stage", type=int, default=7, help="Last stage (1–7)")
    parser.add_argument("--limit", type=int, default=None, help="Process N recipes only")
    parser.add_argument("--skip-llm", action="store_true", help="Skip Stage 6")
    args = parser.parse_args()

    if not args.input:
        logger.error("--input required")
        sys.exit(1)

    # Load recipes
    recipes = []
    with open(args.input, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                recipes.append(json.loads(line))
                if args.limit and len(recipes) >= args.limit:
                    break

    logger.info("Loaded %d recipes from %s", len(recipes), args.input)

    # Run pipeline
    start = time.time()
    recipes = await run_pipeline(
        recipes,
        start_stage=args.start_stage,
        end_stage=args.end_stage,
        skip_llm=args.skip_llm,
    )
    elapsed = time.time() - start

    # Save output
    output_path = args.output or args.input.replace(".jsonl", "_enriched.jsonl")
    with open(output_path, "w", encoding="utf-8") as f:
        for recipe in recipes:
            f.write(json.dumps(recipe, ensure_ascii=False, default=str) + "\n")

    # Summary stats
    statuses = {}
    for r in recipes:
        s = r.get("enrichment_status", "unknown")
        statuses[s] = statuses.get(s, 0) + 1

    logger.info("Pipeline complete in %.1f min", elapsed / 60)
    logger.info("Output: %s (%d recipes)", output_path, len(recipes))
    logger.info("Status distribution: %s", json.dumps(statuses, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
