#!/usr/bin/env python3
"""
enrich_recipes_narrow.py — Stage 6: Narrow-scope LLM enrichment.

Replaces the old enrich_recipes_fast.py which asked the LLM to generate
ALL fields. This script only asks the LLM for fields that genuinely
require language understanding:

  - description (100–200 words, EU/British English)
  - region_tag (sub-national specificity)
  - wine_pairing_notes
  - tips (2–3 practical cooking tips)
  - cultural_notes (1–2 sentences cultural context)
  - pairing_suggestions (2–4 sides/accompaniments)
  - storage_instructions
  - extra_flavor / extra_texture (only if deterministic stage left them empty)

All factual fields (nutrition, dietary, cuisine, difficulty, timing) are
already computed by Stages 1–5 and injected as grounding context.

Usage:
    cd backend && python scripts/enrich_recipes_narrow.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from typing import Any, Optional

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BACKEND_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BACKEND_DIR, ".env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

MODEL = "mistral-small-latest"
BATCH_SIZE = 10          # Recipes per LLM call (smaller = better quality)
CONCURRENCY = 4          # Parallel API calls
MAX_RETRIES = 2
TIMEOUT_SECONDS = 120

# Controlled vocabularies (for extra tags only)
FLAVOR_VOCAB = [
    "umami", "acidic", "sweet", "bitter", "spicy", "herbaceous",
    "smoky", "rich", "light", "tangy", "earthy", "floral", "savoury",
]
TEXTURE_VOCAB = [
    "creamy", "crispy", "tender", "crunchy", "silky", "chunky",
    "fluffy", "chewy", "smooth", "flaky",
]

# ---------------------------------------------------------------------------
# Narrow system prompt — grounded, minimal scope
# ---------------------------------------------------------------------------

NARROW_SYSTEM_PROMPT = f"""You are a culinary writer for a European food app. For each recipe, generate ONLY these fields:

- "desc": A 100–200 word description for a European audience. Use EU/British English (aubergine not eggplant, courgette not zucchini, coriander not cilantro). Mention key flavours, textures, and what makes the dish special. Do NOT mention nutrition values.
- "region": Sub-national region if identifiable (e.g. "Sichuan", "Puglia", "Provence"), else null.
- "wine": 1–2 sentence wine or drink pairing suggestion, else null.
- "tips": Array of 2–3 practical cooking tips for this specific recipe.
- "cultural": 1–2 sentences about the dish's cultural or historical context, or null if generic.
- "pairings": Array of 2–4 suggested sides, accompaniments, or drinks that complement this dish.
- "storage": 1–2 sentences about storage, freezability, and shelf life, or null.
- "extra_flavor": Array of 0–2 additional flavor tags from {json.dumps(FLAVOR_VOCAB)} ONLY if the provided flavor_tags list is empty.
- "extra_texture": Array of 0–2 additional texture tags from {json.dumps(TEXTURE_VOCAB)} ONLY if the provided texture_tags list is empty.

You are given computed context for each recipe including cuisine, dietary info, difficulty, timing, and existing tags. Do NOT contradict this context.
Do NOT generate nutrition, cuisine, difficulty, timing, or dietary information — these are already computed.

Return valid JSON: {{"r": [{{"idx": N, "desc": "...", "region": ..., "wine": ..., "tips": [...], "cultural": ..., "pairings": [...], "storage": ..., "extra_flavor": [...], "extra_texture": [...]}}]}}"""


# ---------------------------------------------------------------------------
# Recipe context formatter — injects all computed fields
# ---------------------------------------------------------------------------

def format_recipe_context(idx: int, recipe: dict[str, Any]) -> str:
    """Format a recipe's computed context for the LLM prompt."""
    title = recipe.get("title", "Untitled")
    cuisine = recipe.get("cuisine_tags", ["Unknown"])
    course = recipe.get("course_tags", [])
    difficulty = recipe.get("difficulty", "?")
    dietary_tags = recipe.get("dietary_tags", [])
    flavor_tags = recipe.get("flavor_tags", [])
    texture_tags = recipe.get("texture_tags", [])
    season_tags = recipe.get("season_tags", [])
    occasion_tags = recipe.get("occasion_tags", [])
    time_total = recipe.get("time_total_min", "?")
    serves = recipe.get("serves", "?")

    # Ingredient names (truncated for token efficiency)
    ingredients = recipe.get("ingredients", [])
    if ingredients and isinstance(ingredients[0], dict):
        ing_names = [i.get("name", "") for i in ingredients]
    elif ingredients and isinstance(ingredients[0], str):
        ing_names = ingredients
    else:
        ing_names = recipe.get("NER", [])
    ing_str = ", ".join(ing_names[:15])

    # Step summary
    steps = recipe.get("steps", [])
    if steps and isinstance(steps[0], dict):
        step_strs = [s.get("instruction", "")[:80] for s in steps[:5]]
    elif steps and isinstance(steps[0], str):
        step_strs = [s[:80] for s in steps[:5]]
    else:
        step_strs = []
    steps_str = " | ".join(step_strs)

    # Technique tags
    tech_tags = set()
    if steps and isinstance(steps[0], dict):
        for s in steps:
            tech_tags.update(s.get("technique_tags", []))
    tech_str = ", ".join(sorted(tech_tags)) if tech_tags else "none detected"

    return (
        f'{idx}. "{title}" | Cuisine: {cuisine} | Course: {course} | '
        f'Difficulty: {difficulty} | Time: {time_total}min | Serves: {serves}\n'
        f'   Ingredients: {ing_str}\n'
        f'   Steps: {steps_str}\n'
        f'   Techniques: {tech_str} | Dietary: {dietary_tags}\n'
        f'   Existing flavor_tags: {flavor_tags} | texture_tags: {texture_tags}\n'
        f'   Season: {season_tags} | Occasion: {occasion_tags}'
    )


# ---------------------------------------------------------------------------
# Batch LLM call
# ---------------------------------------------------------------------------

async def enrich_batch_narrow(
    client: Any,
    batch: list[tuple[int, dict]],
    sem: asyncio.Semaphore,
) -> list[dict]:
    """Call Mistral for a batch of recipes with narrow scope."""
    async with sem:
        lines = [format_recipe_context(idx, recipe) for idx, recipe in batch]
        user_prompt = "\n\n".join(lines)

        messages = [
            {"role": "system", "content": NARROW_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await asyncio.wait_for(
                    client.chat.complete_async(
                        model=MODEL,
                        messages=messages,
                        temperature=0.3,    # Some stylistic variation for descriptions
                        max_tokens=6000,
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
                    for key in ["recipes", "results", "data"]:
                        if key in result and isinstance(result[key], list):
                            return result[key]
                    if "idx" in result or "desc" in result:
                        return [result]
                return []

            except (json.JSONDecodeError, asyncio.TimeoutError, Exception) as e:
                if attempt < MAX_RETRIES:
                    logger.warning(
                        "Batch attempt %d failed: %s — retrying",
                        attempt + 1, str(e)[:100],
                    )
                    await asyncio.sleep(2 + attempt * 2)
                else:
                    logger.error("Batch failed after %d retries: %s", MAX_RETRIES, str(e)[:150])
                    return []

        return []


def expand_narrow_enrichment(e: dict) -> dict:
    """Expand compact keys from narrow LLM response to full field names."""
    return {
        "description": e.get("desc", e.get("description")),
        "region_tag": e.get("region", e.get("region_tag")),
        "wine_pairing_notes": e.get("wine", e.get("wine_pairing_notes")),
        "tips": e.get("tips", []),
        "cultural_notes": e.get("cultural", e.get("cultural_notes")),
        "pairing_suggestions": e.get("pairings", e.get("pairing_suggestions", [])),
        "storage_instructions": e.get("storage", e.get("storage_instructions")),
        "extra_flavor_tags": e.get("extra_flavor", []),
        "extra_texture_tags": e.get("extra_texture", []),
    }


def default_narrow_enrichment(recipe: dict) -> dict:
    """Fallback enrichment when LLM fails."""
    title = recipe.get("title", "this dish")
    return {
        "description": None,
        "region_tag": None,
        "wine_pairing_notes": None,
        "tips": [],
        "cultural_notes": None,
        "pairing_suggestions": [],
        "storage_instructions": None,
        "extra_flavor_tags": [],
        "extra_texture_tags": [],
    }


# ---------------------------------------------------------------------------
# Main pipeline function (can be called from orchestrator)
# ---------------------------------------------------------------------------

async def run_narrow_enrichment(
    recipes: list[dict],
    api_key: str | None = None,
    batch_size: int = BATCH_SIZE,
    concurrency: int = CONCURRENCY,
) -> list[dict]:
    """
    Run narrow LLM enrichment on a batch of recipes.

    Args:
        recipes: List of recipe dicts with all deterministic fields populated.
        api_key: Mistral API key (defaults to env var).
        batch_size: Recipes per LLM call.
        concurrency: Parallel API calls.

    Returns:
        Same recipe list with LLM fields added.
    """
    try:
        from mistralai.client import Mistral
    except ImportError:
        logger.error("mistralai package not installed")
        return recipes

    key = api_key or MISTRAL_API_KEY
    if not key:
        logger.error("MISTRAL_API_KEY not available")
        return recipes

    client = Mistral(api_key=key)
    sem = asyncio.Semaphore(concurrency)

    indexed = list(enumerate(recipes))
    batches = [indexed[i:i + batch_size] for i in range(0, len(indexed), batch_size)]

    logger.info(
        "Narrow LLM enrichment: %d recipes in %d batches (%d concurrent)",
        len(recipes), len(batches), concurrency,
    )
    start = time.time()

    # Process in waves
    wave_size = concurrency * 2
    enrichments: dict[int, dict] = {}

    for wave_start in range(0, len(batches), wave_size):
        wave = batches[wave_start:wave_start + wave_size]
        tasks = [enrich_batch_narrow(client, batch, sem) for batch in wave]
        results = await asyncio.gather(*tasks)

        for batch, batch_results in zip(wave, results):
            result_map = {}
            for r in batch_results:
                idx = r.get("idx", r.get("index"))
                if idx is not None:
                    result_map[idx] = r

            for idx, recipe in batch:
                if idx in result_map:
                    enrichments[idx] = expand_narrow_enrichment(result_map[idx])
                elif idx not in enrichments:
                    enrichments[idx] = default_narrow_enrichment(recipe)

        elapsed = time.time() - start
        done = len(enrichments)
        rate = done / max(elapsed, 1) * 60
        logger.info(
            "%d/%d enriched (%.0f/min, ~%.0f min left)",
            done, len(recipes), rate,
            (len(recipes) - done) / max(rate, 0.1),
        )

    # Apply enrichments
    for idx, recipe in enumerate(recipes):
        e = enrichments.get(idx, default_narrow_enrichment(recipe))

        recipe["description"] = e["description"]
        recipe["region_tag"] = e["region_tag"]
        recipe["wine_pairing_notes"] = e["wine_pairing_notes"]
        recipe["tips"] = e["tips"]
        recipe["cultural_notes"] = e["cultural_notes"]
        recipe["pairing_suggestions"] = e["pairing_suggestions"]
        recipe["storage_instructions"] = e["storage_instructions"]

        # Merge extra tags only if existing tags are empty
        if not recipe.get("flavor_tags") and e["extra_flavor_tags"]:
            recipe["flavor_tags"] = e["extra_flavor_tags"]
        if not recipe.get("texture_tags") and e["extra_texture_tags"]:
            recipe["texture_tags"] = e["extra_texture_tags"]

    logger.info(
        "Narrow enrichment complete: %d recipes in %.1f min",
        len(recipes), (time.time() - start) / 60,
    )
    return recipes


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

async def main():
    """CLI entry point for standalone execution."""
    import argparse

    parser = argparse.ArgumentParser(description="Narrow-scope LLM enrichment")
    parser.add_argument("--input", required=True, help="Input JSONL file")
    parser.add_argument("--output", required=True, help="Output JSONL file")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--concurrency", type=int, default=CONCURRENCY)
    args = parser.parse_args()

    recipes = []
    with open(args.input, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                recipes.append(json.loads(line))

    logger.info("Loaded %d recipes from %s", len(recipes), args.input)

    recipes = await run_narrow_enrichment(
        recipes,
        batch_size=args.batch_size,
        concurrency=args.concurrency,
    )

    with open(args.output, "w", encoding="utf-8") as f:
        for recipe in recipes:
            f.write(json.dumps(recipe, ensure_ascii=False) + "\n")

    logger.info("Saved %d enriched recipes to %s", len(recipes), args.output)


if __name__ == "__main__":
    asyncio.run(main())
