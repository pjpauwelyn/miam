"""
Fast recipe generation using httpx directly for better control over timeouts.
Generates in parallel with smaller batches.
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "data" / "recipes" / "recipes_all.json"
EDGE_CASE_PATH = PROJECT_ROOT / "data" / "recipes" / "edge_cases" / "recipes_edge_cases.json"
PROGRESS_PATH = PROJECT_ROOT / "data" / "recipes" / "progress" / "all_progress.json"

API_KEY = os.environ.get("MISTRAL_API_KEY", "")
API_URL = "https://api.mistral.ai/v1/chat/completions"

CUISINE_DISTRIBUTION = {
    "Italian": 45, "French": 30, "Japanese": 36, "Thai": 30,
    "Dutch/Belgian": 24, "Spanish": 24, "German": 24, "Indian": 24,
    "Middle Eastern": 24, "Scandinavian": 15, "North African": 12,
    "Latin American": 12,
}

COMPACT_PROMPT = """Generate {count} {cuisine} recipes as a JSON array. Each recipe:
{{"title":"name","cuisine_tags":["{cuisine}"],"region_tag":"region","description":"2 sentences","ingredients":[{{"name":"EU English name","amount":200,"unit":"g","is_optional":false}}],"steps":[{{"step_number":1,"instruction":"text","duration_min":5,"technique_tags":["sauté"]}}],"time_prep_min":15,"time_cook_min":25,"time_total_min":40,"serves":4,"difficulty":2,"flavor_tags":["savoury"],"texture_tags":["crispy"],"dietary_tags":["vegetarian"],"dietary_flags":{{"is_vegan":false,"is_vegetarian":true,"is_pescatarian_ok":true,"is_dairy_free":false,"is_gluten_free":true,"is_nut_free":true,"is_halal_ok":true,"contains_pork":false,"contains_shellfish":false,"contains_alcohol":false}},"nutrition_per_serving":{{"kcal":380,"protein_g":12,"fat_g":18,"carbs_g":42,"fiber_g":6,"sugar_g":8,"salt_g":1.2}},"season_tags":["summer"],"occasion_tags":["weeknight-dinner"],"course_tags":["main"],"wine_pairing_notes":"pairing note","tips":["tip"]}}
Metric units. EU English (aubergine, coriander, courgette). Diverse difficulty/occasions. Output ONLY the JSON array."""


def enrich(r: dict, cuisine: str) -> dict:
    r["id"] = str(uuid4())
    r["title_en"] = r.get("title", "")
    r.setdefault("cuisine_tags", [cuisine])
    r.setdefault("region_tag", None)
    r.setdefault("description", f"A traditional {cuisine} dish.")
    df = r.setdefault("dietary_flags", {})
    for k in ["is_vegan","is_vegetarian","is_pescatarian_ok","is_dairy_free","is_gluten_free",
              "is_nut_free","is_halal_ok","contains_pork","contains_shellfish","contains_alcohol"]:
        df.setdefault(k, False)
    df.setdefault("vegan_if_substituted", False)
    df.setdefault("gluten_free_if_substituted", False)
    n = r.setdefault("nutrition_per_serving", {})
    for k in ["kcal","protein_g","fat_g","saturated_fat_g","carbs_g","fiber_g","sugar_g","salt_g"]:
        n.setdefault(k, 0)
    for ing in r.get("ingredients", []):
        ing.setdefault("notes", None)
        ing.setdefault("is_optional", False)
        ing.setdefault("substitutions", [])
    for step in r.get("steps", []):
        step.setdefault("duration_min", None)
        step.setdefault("technique_tags", [])
    r.setdefault("image_placeholder", "")
    r["source_type"] = "mock_tier0"
    # Build embedding text
    parts = [r.get("title",""), r.get("description","")]
    parts += [i.get("name","") for i in r.get("ingredients",[]) if isinstance(i,dict)]
    parts += r.get("flavor_tags",[]) + r.get("cuisine_tags",[]) + r.get("season_tags",[])
    r["embedding_text"] = " ".join(filter(None, parts))
    r["created_at"] = datetime.now(timezone.utc).isoformat()
    r["data_quality_score"] = 0.9
    r.setdefault("wine_pairing_notes", None)
    r.setdefault("tips", [])
    r.setdefault("season_tags", ["year-round"])
    r.setdefault("occasion_tags", [])
    r.setdefault("course_tags", [])
    return r


def inject_edge_cases(recipes: list[dict]) -> list[dict]:
    edge = []
    for i in range(min(10, len(recipes))):
        r = json.loads(json.dumps(recipes[i]))
        r["id"] = str(uuid4())
        r["nutrition_per_serving"] = {"kcal":0,"protein_g":0,"fat_g":0,"saturated_fat_g":0,"carbs_g":0,"fiber_g":0,"sugar_g":0,"salt_g":0}
        r["data_quality_score"] = 0.3
        r["title"] = f"[EDGE-no-nutrition] {r['title']}"
        edge.append(r)
    for i in range(min(5, len(recipes)-10)):
        r = json.loads(json.dumps(recipes[10+i]))
        r["id"] = str(uuid4())
        r["ingredients"] = r.get("ingredients",[])[:1]
        r["data_quality_score"] = 0.2
        r["title"] = f"[EDGE-sparse] {r['title']}"
        edge.append(r)
    for i in range(min(5, len(recipes)-15)):
        r = json.loads(json.dumps(recipes[15+i]))
        r["id"] = str(uuid4())
        r["steps"] = []
        r["data_quality_score"] = 0.15
        r["title"] = f"[EDGE-no-steps] {r['title']}"
        edge.append(r)
    for i in range(min(5, len(recipes)-20)):
        r = json.loads(json.dumps(recipes[20+i]))
        r["id"] = str(uuid4())
        r["dietary_flags"]["is_vegan"] = True
        r["data_quality_score"] = 0.25
        r["title"] = f"[EDGE-contradictory] {r['title']}"
        edge.append(r)
    for i in range(min(5, len(recipes)-25)):
        r = json.loads(json.dumps(recipes[25+i]))
        r["id"] = str(uuid4())
        r["time_total_min"] = 360
        r["time_cook_min"] = 300
        r["data_quality_score"] = 0.4
        r["title"] = f"[EDGE-long-cook] {r['title']}"
        edge.append(r)
    return edge


async def call_mistral(client: httpx.AsyncClient, cuisine: str, count: int) -> list[dict]:
    prompt = COMPACT_PROMPT.format(cuisine=cuisine, count=count)
    for attempt in range(3):
        try:
            resp = await client.post(
                API_URL,
                headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "mistral-small-latest",
                    "messages": [
                        {"role": "system", "content": "Output only valid JSON arrays."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.8,
                    "max_tokens": 8000,
                },
                timeout=90.0,
            )
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            # Strip markdown
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:])
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
            recipes = json.loads(content)
            if not isinstance(recipes, list):
                recipes = [recipes]
            return [enrich(r, cuisine) for r in recipes]
        except Exception as e:
            print(f"    Attempt {attempt+1}/3 failed: {type(e).__name__}: {str(e)[:100]}")
            await asyncio.sleep(2)
    return []


async def main():
    Path(PROGRESS_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(EDGE_CASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    
    # Load progress
    all_recipes = []
    if PROGRESS_PATH.exists():
        with open(PROGRESS_PATH) as f:
            all_recipes = json.load(f)
        print(f"Resuming from {len(all_recipes)} recipes")
    
    # Count existing by cuisine
    existing = {}
    for r in all_recipes:
        for t in r.get("cuisine_tags", []):
            existing[t] = existing.get(t, 0) + 1
    
    # Use a single long-lived client with connection pooling
    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as client:
        for cuisine, target in CUISINE_DISTRIBUTION.items():
            have = existing.get(cuisine, 0)
            need = target - have
            if need <= 0:
                print(f"{cuisine}: {have}/{target} (done)")
                continue
            
            print(f"\n{cuisine}: need {need} more (have {have}/{target})")
            generated = 0
            
            while generated < need:
                batch_size = min(5, need - generated)
                print(f"  Generating {batch_size} {cuisine} recipes...")
                
                batch = await call_mistral(client, cuisine, batch_size)
                if batch:
                    all_recipes.extend(batch)
                    generated += len(batch)
                    existing[cuisine] = have + generated
                    print(f"  +{len(batch)} recipes. {cuisine}: {have+generated}/{target}. Total: {len(all_recipes)}")
                    
                    # Save progress
                    with open(PROGRESS_PATH, "w") as f:
                        json.dump(all_recipes, f)
                else:
                    print(f"  Failed, skipping")
                    break
                
                await asyncio.sleep(0.5)
    
    print(f"\n=== Generated {len(all_recipes)} base recipes ===")
    
    # Edge cases
    edge = inject_edge_cases(all_recipes)
    print(f"Injected {len(edge)} edge cases")
    
    final = all_recipes + edge
    
    with open(OUTPUT_PATH, "w") as f:
        json.dump(final, f, indent=2)
    print(f"Saved {len(final)} total to {OUTPUT_PATH}")
    
    with open(EDGE_CASE_PATH, "w") as f:
        json.dump(edge, f, indent=2)
    print(f"Saved {len(edge)} edge cases to {EDGE_CASE_PATH}")
    
    # Distribution
    from collections import Counter
    dist = Counter()
    for r in final:
        for t in r.get("cuisine_tags", []):
            dist[t] += 1
    print("\nDistribution:")
    for c, n in dist.most_common():
        print(f"  {c}: {n} (target: {CUISINE_DISTRIBUTION.get(c, '?')})")


if __name__ == "__main__":
    asyncio.run(main())
