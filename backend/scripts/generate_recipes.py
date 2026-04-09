"""
Generate 300 mock recipes via Mistral Small for miam Phase 0.

Cuisine distribution (300 total):
  Italian: 15% = 45, French: 10% = 30, Japanese: 12% = 36,
  Thai: 10% = 30, Dutch/Belgian: 8% = 24, Spanish: 8% = 24,
  German: 8% = 24, Indian: 8% = 24, Middle Eastern: 8% = 24,
  Scandinavian: 5% = 15, North African: 4% = 12, Latin American: 4% = 12
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4
from datetime import datetime

from mistralai.client import Mistral

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "data" / "recipes" / "recipes_all.json"
EDGE_CASE_PATH = PROJECT_ROOT / "data" / "recipes" / "edge_cases" / "recipes_edge_cases.json"
PROGRESS_DIR = PROJECT_ROOT / "data" / "recipes" / "progress"

API_KEY = os.environ.get("MISTRAL_API_KEY", "")

CUISINE_DISTRIBUTION = {
    "Italian": 45, "French": 30, "Japanese": 36, "Thai": 30,
    "Dutch/Belgian": 24, "Spanish": 24, "German": 24, "Indian": 24,
    "Middle Eastern": 24, "Scandinavian": 15, "North African": 12,
    "Latin American": 12,
}

GENERATION_PROMPT = """Generate exactly {count} authentic {cuisine} recipes as a JSON array.

Each recipe object must have EXACTLY these fields:
{{
  "title": "Recipe name in English",
  "cuisine_tags": ["{cuisine}"],
  "region_tag": "specific region if applicable",
  "description": "2-3 sentences",
  "ingredients": [
    {{"name": "ingredient name (EU/British English: aubergine not eggplant, coriander not cilantro, courgette not zucchini)", "amount": 200, "unit": "g", "is_optional": false}}
  ],
  "steps": [
    {{"step_number": 1, "instruction": "Step text", "duration_min": 5, "technique_tags": ["sauté"]}}
  ],
  "time_prep_min": 15,
  "time_cook_min": 25,
  "time_total_min": 40,
  "serves": 4,
  "difficulty": 2,
  "flavor_tags": ["savoury", "umami"],
  "texture_tags": ["crispy"],
  "dietary_tags": ["vegetarian"],
  "dietary_flags": {{
    "is_vegan": false, "is_vegetarian": true, "is_pescatarian_ok": true,
    "is_dairy_free": false, "is_gluten_free": true, "is_nut_free": true,
    "is_halal_ok": true, "contains_pork": false, "contains_shellfish": false,
    "contains_alcohol": false
  }},
  "nutrition_per_serving": {{
    "kcal": 380, "protein_g": 12, "fat_g": 18, "carbs_g": 42,
    "fiber_g": 6, "sugar_g": 8, "salt_g": 1.2
  }},
  "season_tags": ["summer"],
  "occasion_tags": ["weeknight-dinner"],
  "course_tags": ["main"],
  "wine_pairing_notes": "A crisp white pairs well.",
  "tips": ["Use day-old bread for better texture"]
}}

RULES:
- All measurements metric (g, ml, °C)
- EU/British English ingredient names
- Make recipes diverse in difficulty (1-5), time, and occasion
- Include a mix of starters, mains, sides, desserts
- Set dietary_flags accurately based on actual ingredients
- {count} recipes total, as a JSON array

Respond with ONLY the JSON array, no markdown formatting."""


def build_embedding_text(r: dict) -> str:
    """Build embedding text for a recipe."""
    parts = [
        r.get("title", ""),
        r.get("description", ""),
        " ".join(i.get("name", "") for i in r.get("ingredients", []) if isinstance(i, dict)),
        " ".join(r.get("flavor_tags", [])),
        " ".join(r.get("texture_tags", [])),
        " ".join(r.get("dietary_tags", [])),
        " ".join(r.get("season_tags", [])),
        " ".join(r.get("cuisine_tags", [])),
        " ".join(r.get("occasion_tags", [])),
    ]
    return " ".join(filter(None, parts))


def enrich_recipe(r: dict, cuisine: str) -> dict:
    """Add miam-specific fields to a generated recipe."""
    r["id"] = str(uuid4())
    r["title_en"] = r.get("title", "")
    if "cuisine_tags" not in r or not r["cuisine_tags"]:
        r["cuisine_tags"] = [cuisine]
    if "dietary_flags" not in r:
        r["dietary_flags"] = {
            "is_vegan": False, "is_vegetarian": False, "is_pescatarian_ok": False,
            "is_dairy_free": False, "is_gluten_free": False, "is_nut_free": True,
            "is_halal_ok": True, "contains_pork": False, "contains_shellfish": False,
            "contains_alcohol": False, "vegan_if_substituted": False, "gluten_free_if_substituted": False,
        }
    else:
        r["dietary_flags"].setdefault("vegan_if_substituted", False)
        r["dietary_flags"].setdefault("gluten_free_if_substituted", False)
    if "nutrition_per_serving" not in r:
        r["nutrition_per_serving"] = {
            "kcal": 0, "protein_g": 0, "fat_g": 0, "saturated_fat_g": 0,
            "carbs_g": 0, "fiber_g": 0, "sugar_g": 0, "salt_g": 0,
        }
    else:
        r["nutrition_per_serving"].setdefault("saturated_fat_g", 0)
    # Ensure ingredients have all fields
    for ing in r.get("ingredients", []):
        ing.setdefault("notes", None)
        ing.setdefault("is_optional", False)
        ing.setdefault("substitutions", [])
    # Ensure steps have all fields  
    for step in r.get("steps", []):
        step.setdefault("duration_min", None)
        step.setdefault("technique_tags", [])
    r.setdefault("image_placeholder", "")
    r["source_type"] = "mock_tier0"
    r["embedding_text"] = build_embedding_text(r)
    r["created_at"] = datetime.utcnow().isoformat() + "Z"
    r["data_quality_score"] = 0.9
    r.setdefault("region_tag", None)
    r.setdefault("wine_pairing_notes", None)
    r.setdefault("tips", [])
    r.setdefault("season_tags", ["year-round"])
    r.setdefault("occasion_tags", [])
    r.setdefault("course_tags", [])
    return r


def inject_edge_cases(recipes: list[dict]) -> list[dict]:
    """Inject 30 intentionally noisy records for refinement agent testing."""
    edge_cases = []
    
    # 10 recipes with zeroed nutrition
    for i in range(10):
        if i < len(recipes):
            r = recipes[i].copy()
            r["id"] = str(uuid4())
            r["nutrition_per_serving"] = {
                "kcal": 0, "protein_g": 0, "fat_g": 0, "saturated_fat_g": 0,
                "carbs_g": 0, "fiber_g": 0, "sugar_g": 0, "salt_g": 0,
            }
            r["data_quality_score"] = 0.3
            r["data_quality_notes"] = "Edge case: missing nutrition data"
            r["title"] = f"[EDGE] {r['title']}"
            edge_cases.append(r)

    # 5 recipes with only 1-2 ingredients
    for i in range(5):
        idx = 10 + i
        if idx < len(recipes):
            r = recipes[idx].copy()
            r["id"] = str(uuid4())
            r["ingredients"] = r.get("ingredients", [])[:2]
            r["data_quality_score"] = 0.2
            r["data_quality_notes"] = "Edge case: sparse ingredients"
            r["title"] = f"[EDGE] {r['title']}"
            edge_cases.append(r)

    # 5 recipes with only title + ingredients (empty steps)
    for i in range(5):
        idx = 15 + i
        if idx < len(recipes):
            r = recipes[idx].copy()
            r["id"] = str(uuid4())
            r["steps"] = []
            r["data_quality_score"] = 0.15
            r["data_quality_notes"] = "Edge case: no steps"
            r["title"] = f"[EDGE] {r['title']}"
            edge_cases.append(r)

    # 5 recipes with contradictory dietary flags
    for i in range(5):
        idx = 20 + i
        if idx < len(recipes):
            r = recipes[idx].copy()
            r["id"] = str(uuid4())
            r["dietary_flags"]["is_vegan"] = True  # Contradicts butter/cream in ingredients
            r["data_quality_score"] = 0.25
            r["data_quality_notes"] = "Edge case: contradictory dietary flags"
            r["title"] = f"[EDGE] {r['title']}"
            edge_cases.append(r)

    # 5 recipes with abnormally high cook time
    for i in range(5):
        idx = 25 + i
        if idx < len(recipes):
            r = recipes[idx].copy()
            r["id"] = str(uuid4())
            r["time_total_min"] = 360
            r["time_cook_min"] = 300
            r["data_quality_score"] = 0.4
            r["data_quality_notes"] = "Edge case: abnormally long cook time"
            r["title"] = f"[EDGE] {r['title']}"
            edge_cases.append(r)

    return edge_cases


async def generate_batch(client: Mistral, cuisine: str, count: int, attempt: int = 1) -> list[dict]:
    """Generate a batch of recipes for a cuisine. Retries up to 3 times."""
    prompt = GENERATION_PROMPT.format(cuisine=cuisine, count=count)
    
    for retry in range(3):
        try:
            response = await asyncio.wait_for(
                client.chat.complete_async(
                    model="mistral-small-latest",
                    messages=[
                        {"role": "system", "content": "You are a recipe database generator. Output only valid JSON arrays."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.8,
                    max_tokens=8000,
                ),
                timeout=120.0,  # 2 minute timeout
            )
            
            content = response.choices[0].message.content.strip()
            
            # Clean markdown formatting if present
            if content.startswith("```"):
                content = content.split("\n", 1)[1] if "\n" in content else content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
            
            recipes = json.loads(content)
            if not isinstance(recipes, list):
                recipes = [recipes]
            
            # Enrich each recipe
            enriched = [enrich_recipe(r, cuisine) for r in recipes]
            return enriched

        except asyncio.TimeoutError:
            print(f"    Timeout on attempt {retry+1}/3 for {cuisine}")
            await asyncio.sleep(2)
        except json.JSONDecodeError as e:
            print(f"    JSON parse error on attempt {retry+1}/3: {e}")
            await asyncio.sleep(1)
        except Exception as e:
            print(f"    Error on attempt {retry+1}/3: {e}")
            await asyncio.sleep(2)
    
    print(f"    All retries exhausted for {cuisine} batch")
    return []


async def main():
    PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "data" / "recipes" / "edge_cases").mkdir(parents=True, exist_ok=True)
    
    client = Mistral(api_key=API_KEY)
    all_recipes = []
    
    # Check for existing progress
    progress_file = PROGRESS_DIR / "all_progress.json"
    if progress_file.exists():
        with open(progress_file) as f:
            all_recipes = json.load(f)
        print(f"Resuming from {len(all_recipes)} existing recipes")
    
    # Track what we already have by cuisine
    existing_cuisines = {}
    for r in all_recipes:
        for tag in r.get("cuisine_tags", []):
            existing_cuisines[tag] = existing_cuisines.get(tag, 0) + 1
    
    total_target = sum(CUISINE_DISTRIBUTION.values())
    
    for cuisine, target in CUISINE_DISTRIBUTION.items():
        existing = existing_cuisines.get(cuisine, 0)
        needed = target - existing
        
        if needed <= 0:
            print(f"{cuisine}: Already have {existing}/{target}")
            continue
        
        print(f"\n{cuisine}: Generating {needed} recipes (have {existing}/{target})...")
        
        # Generate in batches of 5
        batch_size = 5
        generated = 0
        
        while generated < needed:
            this_batch = min(batch_size, needed - generated)
            print(f"  Batch: generating {this_batch} {cuisine} recipes...")
            
            batch = await generate_batch(client, cuisine, this_batch)
            
            if batch:
                all_recipes.extend(batch)
                generated += len(batch)
                print(f"  Got {len(batch)} recipes. Total {cuisine}: {existing + generated}/{target}. Overall: {len(all_recipes)}/{total_target}")
                
                # Save progress
                with open(progress_file, "w") as f:
                    json.dump(all_recipes, f, indent=2)
            else:
                print(f"  Failed to generate batch, moving on")
                break
            
            # Small delay to avoid rate limits
            await asyncio.sleep(1)
    
    print(f"\n=== Generation complete: {len(all_recipes)} recipes ===")
    
    # Inject edge cases
    print("\nInjecting 30 edge case recipes...")
    edge_cases = inject_edge_cases(all_recipes)
    print(f"Created {len(edge_cases)} edge cases")
    
    # Combine
    final_recipes = all_recipes + edge_cases
    
    # Save final output
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(final_recipes, f, indent=2)
    print(f"\nSaved {len(final_recipes)} total recipes to {OUTPUT_PATH}")
    
    # Save edge cases separately
    with open(EDGE_CASE_PATH, "w", encoding="utf-8") as f:
        json.dump(edge_cases, f, indent=2)
    print(f"Saved {len(edge_cases)} edge cases to {EDGE_CASE_PATH}")
    
    # Print distribution
    print("\nCuisine distribution:")
    from collections import Counter
    dist = Counter()
    for r in final_recipes:
        for tag in r.get("cuisine_tags", []):
            dist[tag] += 1
    for cuisine, count in dist.most_common():
        target = CUISINE_DISTRIBUTION.get(cuisine, 0)
        print(f"  {cuisine}: {count} (target: {target})")


if __name__ == "__main__":
    asyncio.run(main())
