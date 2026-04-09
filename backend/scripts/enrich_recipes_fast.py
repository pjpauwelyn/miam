#!/usr/bin/env python3
"""
enrich_recipes_fast.py — Parallel batch LLM enrichment of 2,000 recipes.

Uses concurrent async tasks to process multiple batches in parallel.
Resumes from progress file if interrupted.

Exception: This script calls the Mistral client directly for batch efficiency
(per handoff Section 8). API key read from environment variables, never hardcoded.

Usage:
    cd backend && python ../scripts/enrich_recipes_fast.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from typing import Optional

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, BACKEND_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BACKEND_DIR, ".env"))

from mistralai.client import Mistral

from services.nutrition_lookup import NutritionLookup
from services.dietary_inference import DietaryInferenceEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "open")
INPUT_PATH = os.path.join(DATA_DIR, "recipenlg_subset_2000.jsonl")
OUTPUT_PATH = os.path.join(DATA_DIR, "recipenlg_enriched_2000.jsonl")
PROGRESS_PATH = os.path.join(DATA_DIR, "_enrichment_progress.json")

MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
MODEL = "mistral-small-latest"
BATCH_SIZE = 15  # Recipes per LLM call
CONCURRENCY = 5  # Parallel API calls
MAX_RETRIES = 2
TIMEOUT_SECONDS = 90

# Controlled vocabularies
FLAVOR_VOCAB = ["umami", "acidic", "sweet", "bitter", "spicy", "herbaceous", "smoky", "rich", "light", "tangy", "earthy", "floral", "savoury"]
TEXTURE_VOCAB = ["creamy", "crispy", "tender", "crunchy", "silky", "chunky", "fluffy", "chewy", "smooth", "flaky"]
SEASON_VOCAB = ["spring", "summer", "autumn", "winter", "year-round"]
OCCASION_VOCAB = ["weeknight", "dinner-party", "date-night", "comfort-food", "meal-prep", "brunch", "quick-lunch", "festive"]
COURSE_VOCAB = ["starter", "main", "side", "dessert", "snack", "breakfast", "soup", "salad"]
CUISINE_VOCAB = ["Italian", "French", "Spanish", "Greek", "Moroccan", "Lebanese", "Turkish", "Indian", "Chinese", "Japanese", "Korean", "Thai", "Vietnamese", "Mexican", "Peruvian", "American", "British", "German", "Dutch", "Scandinavian", "Middle Eastern", "African", "Caribbean", "Fusion", "Other"]

SYSTEM_PROMPT = f"""You are a culinary expert. For each recipe, return a JSON object:
- "idx": recipe index (integer)
- "desc": 1-2 sentence description for European audience
- "diff": difficulty 1-5
- "cuis": cuisine from {json.dumps(CUISINE_VOCAB)}
- "flav": 2-3 from {json.dumps(FLAVOR_VOCAB)}
- "text": 1-2 from {json.dumps(TEXTURE_VOCAB)}
- "seas": 1-2 from {json.dumps(SEASON_VOCAB)}
- "occ": 1-2 from {json.dumps(OCCASION_VOCAB)}
- "cour": 1-2 from {json.dumps(COURSE_VOCAB)}
- "prep": prep minutes (int)
- "cook": cook minutes (int)
- "serv": servings (int)

Return a JSON object with key "r" containing an array of these objects. Use EU/British English."""


def load_recipes(path: str) -> list[dict]:
    recipes = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                recipes.append(json.loads(line))
    return recipes


def load_progress() -> dict:
    if os.path.exists(PROGRESS_PATH):
        with open(PROGRESS_PATH, "r") as f:
            return json.load(f)
    return {"completed_indices": [], "enrichments": {}}


def save_progress(progress: dict) -> None:
    with open(PROGRESS_PATH, "w") as f:
        json.dump(progress, f)


async def enrich_batch(client: Mistral, batch: list[tuple[int, dict]], sem: asyncio.Semaphore) -> list[dict]:
    """Call Mistral for a batch of recipes, respecting concurrency."""
    async with sem:
        lines = []
        for idx, recipe in batch:
            title = recipe["title"]
            ner = ", ".join(recipe.get("NER", [])[:15])
            steps = " | ".join(d[:80] for d in recipe.get("directions", [])[:6])
            lines.append(f'{idx}. "{title}" — {ner} — {steps}')

        user_prompt = "\n".join(lines)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await asyncio.wait_for(
                    client.chat.complete_async(
                        model=MODEL,
                        messages=messages,
                        temperature=0,
                        max_tokens=4000,
                        response_format={"type": "json_object"},
                    ),
                    timeout=TIMEOUT_SECONDS,
                )
                content = response.choices[0].message.content.strip()
                result = json.loads(content)

                if isinstance(result, dict) and "r" in result:
                    return result["r"]
                elif isinstance(result, list):
                    return result
                elif isinstance(result, dict):
                    for key in ["recipes", "results", "data", "enrichments"]:
                        if key in result and isinstance(result[key], list):
                            return result[key]
                    if "idx" in result or "desc" in result:
                        return [result]
                return []

            except (json.JSONDecodeError, asyncio.TimeoutError, Exception) as e:
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(1 + attempt)
                else:
                    logger.warning("Batch failed after retries: %s", str(e)[:100])
                    return []

        return []


def default_enrichment(idx: int, recipe: dict) -> dict:
    return {
        "idx": idx, "desc": f"A tasty recipe for {recipe['title']}.",
        "diff": 2, "cuis": recipe.get("_cuisine", "Other"),
        "flav": ["savoury"], "text": ["tender"], "seas": ["year-round"],
        "occ": ["weeknight"], "cour": ["main"], "prep": 15, "cook": 30, "serv": 4,
    }


def expand_enrichment(e: dict) -> dict:
    """Expand compact keys to full field names."""
    return {
        "description": e.get("desc", e.get("description", "")),
        "difficulty": e.get("diff", e.get("difficulty", 2)),
        "cuisine": e.get("cuis", e.get("cuisine", "Other")),
        "flavor_tags": e.get("flav", e.get("flavor_tags", [])),
        "texture_tags": e.get("text", e.get("texture_tags", [])),
        "season_tags": e.get("seas", e.get("season_tags", [])),
        "occasion_tags": e.get("occ", e.get("occasion_tags", [])),
        "course_tags": e.get("cour", e.get("course_tags", [])),
        "time_prep_min": e.get("prep", e.get("time_prep_min", 15)),
        "time_cook_min": e.get("cook", e.get("time_cook_min", 30)),
        "serves": e.get("serv", e.get("serves", 4)),
    }


async def main():
    if not MISTRAL_API_KEY:
        logger.error("MISTRAL_API_KEY not set")
        sys.exit(1)

    client = Mistral(api_key=MISTRAL_API_KEY)
    nl = NutritionLookup()
    dietary_engine = DietaryInferenceEngine()

    recipes = load_recipes(INPUT_PATH)
    logger.info("Loaded %d recipes", len(recipes))

    progress = load_progress()
    completed = set(progress.get("completed_indices", []))
    enrichments = progress.get("enrichments", {})
    logger.info("Already enriched: %d", len(completed))

    remaining = [(i, r) for i, r in enumerate(recipes) if i not in completed]
    logger.info("Remaining: %d", len(remaining))

    if remaining:
        sem = asyncio.Semaphore(CONCURRENCY)
        batches = []
        for i in range(0, len(remaining), BATCH_SIZE):
            batches.append(remaining[i:i + BATCH_SIZE])

        logger.info("Processing %d batches (%d concurrent)...", len(batches), CONCURRENCY)
        start = time.time()

        # Process in waves of CONCURRENCY * 3 batches
        wave_size = CONCURRENCY * 3
        for wave_start in range(0, len(batches), wave_size):
            wave = batches[wave_start:wave_start + wave_size]
            tasks = [enrich_batch(client, batch, sem) for batch in wave]
            results = await asyncio.gather(*tasks)

            for batch, batch_results in zip(wave, results):
                result_map = {}
                for r in batch_results:
                    idx = r.get("idx", r.get("index"))
                    if idx is not None:
                        result_map[idx] = r

                for idx, recipe in batch:
                    if idx in result_map:
                        enrichments[str(idx)] = result_map[idx]
                    elif str(idx) not in enrichments:
                        enrichments[str(idx)] = default_enrichment(idx, recipe)
                    completed.add(idx)

            # Save progress
            progress["completed_indices"] = list(completed)
            progress["enrichments"] = enrichments
            save_progress(progress)

            elapsed = time.time() - start
            done = len(completed)
            rate = done / max(elapsed, 1) * 60
            logger.info(
                "%d/%d enriched (%.0f/min, ~%.0f min left)",
                done, len(recipes), rate,
                (len(recipes) - done) / max(rate, 0.1)
            )

    # Apply nutrition and dietary flags
    logger.info("Applying nutrition + dietary flags...")
    nl.reset_stats()
    enriched_out = []

    for i, recipe in enumerate(recipes):
        raw_e = enrichments.get(str(i), default_enrichment(i, recipe))
        e = expand_enrichment(raw_e)
        recipe["_enrichment"] = e

        # Nutrition
        ner = recipe.get("NER", [])
        serves = e.get("serves", 4) or 4
        total_nutr = {"kcal": 0, "protein_g": 0, "fat_g": 0, "saturated_fat_g": 0,
                      "carbs_g": 0, "fiber_g": 0, "sugar_g": 0, "salt_g": 0}
        matched = 0
        for name in ner:
            r = nl.lookup(name)
            if r:
                matched += 1
                total_nutr["kcal"] += r.kcal
                total_nutr["protein_g"] += r.protein_g
                total_nutr["fat_g"] += r.fat_g
                total_nutr["saturated_fat_g"] += r.saturated_fat_g
                total_nutr["carbs_g"] += r.carbs_g
                total_nutr["fiber_g"] += r.fiber_g
                total_nutr["sugar_g"] += r.sugar_g
                total_nutr["salt_g"] += r.salt_g

        if matched > 0:
            recipe["_nutrition"] = {
                "kcal": max(1, int(total_nutr["kcal"] / serves)),
                "protein_g": round(total_nutr["protein_g"] / serves, 1),
                "fat_g": round(total_nutr["fat_g"] / serves, 1),
                "saturated_fat_g": round(total_nutr["saturated_fat_g"] / serves, 1),
                "carbs_g": round(total_nutr["carbs_g"] / serves, 1),
                "fiber_g": round(total_nutr["fiber_g"] / serves, 1),
                "sugar_g": round(total_nutr["sugar_g"] / serves, 1),
                "salt_g": round(total_nutr["salt_g"] / serves, 2),
            }
        else:
            recipe["_nutrition"] = None

        # Dietary flags
        flags = dietary_engine.infer_flags(ner)
        recipe["_dietary_flags"] = {
            "is_vegan": flags.is_vegan, "is_vegetarian": flags.is_vegetarian,
            "is_pescatarian_ok": flags.is_pescatarian_ok, "is_dairy_free": flags.is_dairy_free,
            "is_gluten_free": flags.is_gluten_free, "is_nut_free": flags.is_nut_free,
            "is_halal_ok": flags.is_halal_ok, "contains_pork": flags.contains_pork,
            "contains_shellfish": flags.contains_shellfish, "contains_alcohol": flags.contains_alcohol,
            "vegan_if_substituted": flags.vegan_if_substituted,
            "gluten_free_if_substituted": flags.gluten_free_if_substituted,
        }
        recipe["_dietary_tags"] = dietary_engine.dietary_tags_from_flags(flags)

        enriched_out.append(recipe)

    logger.info("Nutrition: %.1f%% coverage (%d/%d)",
                nl.coverage_rate(), nl.stats["total"] - nl.stats["miss"], nl.stats["total"])

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for recipe in enriched_out:
            f.write(json.dumps(recipe, ensure_ascii=False) + "\n")

    logger.info("Saved %d enriched recipes to %s", len(enriched_out), OUTPUT_PATH)
    if os.path.exists(PROGRESS_PATH):
        os.remove(PROGRESS_PATH)


if __name__ == "__main__":
    asyncio.run(main())
