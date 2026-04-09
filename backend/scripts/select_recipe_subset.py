#!/usr/bin/env python3
"""
select_recipe_subset.py — Filter 60K RecipeNLG → 2,000 balanced subset.

Strategy:
1. Load 60K filtered RecipeNLG records
2. Apply dietary inference (free, rule-based) to all records
3. Apply keyword-based cuisine heuristic (fast, no LLM needed)
4. Score each recipe for quality
5. Select 2,000 balanced across cuisines, courses, and dietary diversity
6. Save as /data/open/recipenlg_subset_2000.jsonl

The LLM cuisine classifier will run during the enrichment phase for
higher accuracy on the final 2,000 recipes only.

Usage:
    cd backend && python ../scripts/select_recipe_subset.py
"""
from __future__ import annotations

import json
import logging
import os
import random
import sys
from collections import Counter, defaultdict

# Set up paths
BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, BACKEND_DIR)

from services.dietary_inference import DietaryInferenceEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Paths
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "open")
INPUT_PATH = os.path.join(DATA_DIR, "recipenlg_filtered.jsonl")
OUTPUT_PATH = os.path.join(DATA_DIR, "recipenlg_subset_2000.jsonl")

# Target total
TARGET_TOTAL = 2000

# Minimum dietary diversity targets
MIN_VEGAN = 200
MIN_VEGETARIAN = 300  # includes vegan
MIN_GLUTEN_FREE = 100

# -----------------------------------------------------------------------
# Keyword-based cuisine heuristic
# -----------------------------------------------------------------------
# Maps ingredient/title keywords to cuisine labels.
# This is a fast pre-classifier; LLM will refine during enrichment.
CUISINE_KEYWORDS: dict[str, list[str]] = {
    "Italian": [
        "parmesan", "parmigiano", "mozzarella", "ricotta", "mascarpone",
        "basil", "oregano", "prosciutto", "pancetta", "penne", "spaghetti",
        "linguine", "fettuccine", "lasagna", "lasagne", "risotto", "gnocchi",
        "ravioli", "tortellini", "focaccia", "ciabatta", "bruschetta",
        "marinara", "bolognese", "carbonara", "pesto", "tiramisu",
        "antipasto", "polenta", "arancini", "osso buco",
    ],
    "French": [
        "dijon", "brie", "camembert", "gruyère", "gruyere", "roquefort",
        "crème fraîche", "creme fraiche", "bechamel", "béchamel",
        "ratatouille", "coq au vin", "bouillabaisse", "soufflé", "souffle",
        "crêpe", "crepe", "croissant", "baguette", "brioche", "quiche",
        "cassoulet", "confit", "meunière", "provençal", "provencal",
        "herbes de provence", "tarragon", "chervil", "béarnaise",
    ],
    "Spanish": [
        "chorizo", "saffron", "paprika", "manchego", "paella", "gazpacho",
        "tapas", "patatas bravas", "tortilla española", "churros",
        "sangria", "sobrassada", "pimiento", "romesco",
    ],
    "Greek": [
        "feta", "kalamata", "tzatziki", "moussaka", "spanakopita",
        "souvlaki", "gyro", "phyllo", "filo", "halloumi",
        "dolma", "oregano", "olive",
    ],
    "Indian": [
        "curry", "turmeric", "cumin", "garam masala", "cardamom",
        "coriander", "cilantro", "naan", "paneer", "ghee", "chutney",
        "biryani", "tikka", "masala", "tandoori", "dal", "dhal",
        "samosa", "chapati", "roti", "raita", "korma", "vindaloo",
        "tamarind", "fenugreek", "mustard seed",
    ],
    "Chinese": [
        "soy sauce", "hoisin", "oyster sauce", "sesame oil", "five spice",
        "star anise", "szechuan", "sichuan", "wonton", "dim sum",
        "lo mein", "chow mein", "kung pao", "mapo", "stir fry",
        "bok choy", "tofu", "bean sprout", "water chestnut",
        "bamboo shoot", "rice wine", "doubanjiang",
    ],
    "Japanese": [
        "miso", "dashi", "nori", "wasabi", "sake", "mirin",
        "sushi", "sashimi", "tempura", "ramen", "udon", "soba",
        "teriyaki", "ponzu", "edamame", "tofu", "panko",
        "katsu", "mochi", "matcha", "bonito",
    ],
    "Thai": [
        "fish sauce", "lemongrass", "galangal", "kaffir lime",
        "thai basil", "coconut milk", "pad thai", "green curry",
        "red curry", "massaman", "satay", "tom yum", "tom kha",
        "sriracha", "bird eye chili", "palm sugar",
    ],
    "Mexican": [
        "tortilla", "salsa", "jalapeño", "jalapeno", "chipotle",
        "cumin", "enchilada", "taco", "burrito", "quesadilla",
        "guacamole", "avocado", "cilantro", "lime", "black bean",
        "refried bean", "tamale", "mole", "pozole", "chili powder",
        "ancho", "poblano", "queso",
    ],
    "Korean": [
        "gochujang", "gochugaru", "kimchi", "sesame", "doenjang",
        "bibimbap", "bulgogi", "japchae", "tteok", "soju",
        "korean", "banchan", "ssam",
    ],
    "Vietnamese": [
        "fish sauce", "lemongrass", "pho", "banh mi", "spring roll",
        "rice paper", "vietnamese", "nuoc mam", "nuoc cham",
    ],
    "Turkish": [
        "sumac", "pomegranate", "turkish", "lahmacun", "pide",
        "börek", "borek", "baklava", "kebab", "kofte",
        "yoghurt", "bulgur", "za'atar",
    ],
    "Middle Eastern": [
        "tahini", "hummus", "za'atar", "zaatar", "sumac",
        "pomegranate", "chickpea", "flatbread", "falafel",
        "shawarma", "baba ghanoush", "harissa", "preserved lemon",
        "rose water", "pistachio",
    ],
    "Moroccan": [
        "harissa", "ras el hanout", "preserved lemon", "tagine",
        "couscous", "moroccan", "merguez", "argan",
    ],
    "Lebanese": [
        "tabbouleh", "fattoush", "kibbeh", "labneh", "lebanese",
        "za'atar", "sumac", "pomegranate molasses",
    ],
    "British": [
        "worcestershire", "marmite", "stilton", "cheddar",
        "shepherd's pie", "fish and chips", "trifle", "scone",
        "clotted cream", "yorkshire pudding", "spotted dick",
        "bangers", "crumpet",
    ],
    "German": [
        "sauerkraut", "bratwurst", "pretzel", "schnitzel",
        "strudel", "spätzle", "spaetzle", "pumpernickel",
        "german",
    ],
    "Scandinavian": [
        "dill", "lingonberry", "cardamom", "gravlax", "smørrebrød",
        "swedish", "norwegian", "danish", "finnish",
        "meatball", "pickled herring",
    ],
    "Caribbean": [
        "jerk", "allspice", "plantain", "scotch bonnet",
        "caribbean", "jamaican", "coconut",
    ],
    "American": [
        "ranch", "buffalo", "bbq", "barbecue", "cornbread",
        "mac and cheese", "chili con carne", "coleslaw",
        "thanksgiving", "brownie", "cookie", "pancake",
    ],
    "Peruvian": [
        "aji amarillo", "ceviche", "peruvian", "quinoa",
        "purple corn", "lucuma",
    ],
    "African": [
        "berbere", "injera", "fufu", "jollof", "african",
        "piri piri", "peri peri",
    ],
}

# Title-based cuisine keywords (stronger signal than ingredients)
TITLE_CUISINE_KEYWORDS: dict[str, list[str]] = {
    "Italian": ["italian", "pasta", "risotto", "pizza", "lasagna", "lasagne", "gnocchi",
                "bruschetta", "minestrone", "panna cotta", "tiramisu", "carbonara",
                "bolognese", "primavera", "alfredo", "puttanesca", "arrabbiata"],
    "French": ["french", "provençal", "provencal", "gratin", "quiche", "crêpe", "crepe",
               "soufflé", "souffle", "ratatouille", "cassoulet", "bouillabaisse"],
    "Indian": ["indian", "curry", "tikka", "masala", "biryani", "tandoori", "korma",
               "vindaloo", "dal", "dhal", "samosa", "naan"],
    "Chinese": ["chinese", "stir fry", "stir-fry", "lo mein", "chow mein", "kung pao",
                "sweet and sour", "fried rice", "dim sum", "wonton", "dumpling"],
    "Japanese": ["japanese", "sushi", "sashimi", "tempura", "ramen", "teriyaki",
                 "miso", "udon", "soba", "katsu", "mochi", "matcha"],
    "Thai": ["thai", "pad thai", "green curry", "red curry", "tom yum", "tom kha",
             "massaman", "satay"],
    "Mexican": ["mexican", "taco", "burrito", "enchilada", "quesadilla", "fajita",
                "chimichanga", "tamale", "mole", "pozole", "tostada", "nachos"],
    "Korean": ["korean", "kimchi", "bibimbap", "bulgogi", "japchae"],
    "Vietnamese": ["vietnamese", "pho", "banh mi", "spring roll"],
    "Turkish": ["turkish", "kebab", "kofte", "börek", "borek", "baklava"],
    "Greek": ["greek", "moussaka", "spanakopita", "souvlaki", "gyro"],
    "Moroccan": ["moroccan", "tagine", "couscous"],
    "Middle Eastern": ["middle eastern", "hummus", "falafel", "shawarma"],
    "Lebanese": ["lebanese", "tabbouleh", "fattoush", "kibbeh"],
    "Spanish": ["spanish", "paella", "gazpacho", "tapas", "churros"],
    "British": ["british", "english", "fish and chips", "shepherd's pie", "bangers"],
    "German": ["german", "schnitzel", "strudel", "pretzel"],
    "Scandinavian": ["swedish", "norwegian", "danish", "finnish", "scandinavian"],
    "Caribbean": ["caribbean", "jamaican", "jerk"],
    "American": ["american", "southern", "cajun", "creole", "tex-mex"],
    "Peruvian": ["peruvian", "ceviche"],
    "African": ["african", "ethiopian", "nigerian", "west african"],
}


def classify_cuisine_heuristic(recipe: dict) -> str:
    """
    Keyword-based cuisine classification. Fast (no LLM needed).
    Returns the best-matching cuisine tag from the controlled vocabulary.
    """
    title = recipe.get("title", "").lower()
    ner = [n.lower() for n in recipe.get("NER", [])]
    ner_text = " ".join(ner)

    scores: Counter = Counter()

    # Title-based matches (stronger signal, weight = 3)
    for cuisine, keywords in TITLE_CUISINE_KEYWORDS.items():
        for kw in keywords:
            if kw in title:
                scores[cuisine] += 3

    # Ingredient-based matches (weight = 1 per match)
    for cuisine, keywords in CUISINE_KEYWORDS.items():
        for kw in keywords:
            if kw in ner_text or kw in title:
                scores[cuisine] += 1

    if not scores:
        return "Other"

    # Return top cuisine
    top_cuisine, top_score = scores.most_common(1)[0]
    if top_score >= 2:
        return top_cuisine
    return "Other"


def load_recipes(path: str) -> list[dict]:
    """Load JSONL recipes."""
    recipes = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recipes.append(json.loads(line))
    logger.info("Loaded %d recipes from %s", len(recipes), path)
    return recipes


def apply_dietary_flags(recipes: list[dict]) -> list[dict]:
    """Add dietary flags to all recipes using the rule-based engine."""
    engine = DietaryInferenceEngine()
    for recipe in recipes:
        ner = recipe.get("NER", [])
        flags = engine.infer_flags(ner)
        recipe["_dietary_flags"] = {
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
        }
        recipe["_dietary_tags"] = engine.dietary_tags_from_flags(flags)
    return recipes


def score_recipe_quality(recipe: dict) -> float:
    """Score a recipe's quality/diversity potential (0-1)."""
    score = 0.0
    ner = recipe.get("NER", [])
    directions = recipe.get("directions", [])
    title = recipe.get("title", "")

    # Ingredient count (7-15 is ideal)
    n_ing = len(ner)
    if 7 <= n_ing <= 15:
        score += 0.3
    elif 5 <= n_ing <= 20:
        score += 0.2
    else:
        score += 0.1

    # Step count (4-10 is ideal)
    n_steps = len(directions)
    if 4 <= n_steps <= 10:
        score += 0.2
    elif 3 <= n_steps <= 15:
        score += 0.15

    # Title quality
    if 10 <= len(title) <= 60:
        score += 0.2
    elif len(title) > 5:
        score += 0.1

    # Ingredient diversity
    unique_ner = set(n.lower().strip() for n in ner)
    if len(unique_ner) >= 6:
        score += 0.15
    elif len(unique_ner) >= 4:
        score += 0.1

    # Step detail
    if directions:
        avg_step_len = sum(len(d) for d in directions) / len(directions)
        if avg_step_len > 50:
            score += 0.15
        elif avg_step_len > 30:
            score += 0.1

    return min(score, 1.0)


# Target cuisine distribution
TARGET_CUISINE_PCTS: dict[str, float] = {
    "Italian": 0.12, "French": 0.08, "Spanish": 0.05, "Greek": 0.04,
    "Indian": 0.08, "Chinese": 0.07, "Japanese": 0.06, "Thai": 0.05,
    "Mexican": 0.06, "American": 0.08, "British": 0.04, "German": 0.03,
    "Middle Eastern": 0.04, "Korean": 0.03, "Vietnamese": 0.03,
    "Moroccan": 0.02, "Lebanese": 0.02, "Turkish": 0.02,
    "Scandinavian": 0.02, "Caribbean": 0.02, "African": 0.01,
    "Peruvian": 0.01, "Dutch": 0.01, "Fusion": 0.02, "Other": 0.05,
}


def select_balanced_subset(recipes: list[dict]) -> list[dict]:
    """Select 2,000 balanced across cuisines and dietary types."""
    # Group by cuisine
    by_cuisine: dict[str, list[dict]] = defaultdict(list)
    for recipe in recipes:
        cuisine = recipe.get("_cuisine", "Other")
        by_cuisine[cuisine].append(recipe)

    # Sort each group by quality
    for cuisine in by_cuisine:
        by_cuisine[cuisine].sort(key=lambda r: r.get("_quality_score", 0), reverse=True)

    logger.info("Cuisine distribution in full corpus:")
    for cuisine, recs in sorted(by_cuisine.items(), key=lambda x: -len(x[1])):
        logger.info("  %20s: %d", cuisine, len(recs))

    selected: list[dict] = []
    seen_titles: set[str] = set()

    def add_recipe(r: dict) -> bool:
        t = r["title"].lower()
        if t not in seen_titles:
            selected.append(r)
            seen_titles.add(t)
            return True
        return False

    # Phase 1: Fill cuisine slots
    for cuisine, pct in TARGET_CUISINE_PCTS.items():
        n_target = max(10, int(TARGET_TOTAL * pct))
        pool = by_cuisine.get(cuisine, [])
        added = 0
        for r in pool:
            if added >= n_target:
                break
            if add_recipe(r):
                added += 1

    # Phase 2: Ensure dietary minimums
    vegan_count = sum(1 for r in selected if r["_dietary_flags"]["is_vegan"])
    veg_count = sum(1 for r in selected if r["_dietary_flags"]["is_vegetarian"])
    gf_count = sum(1 for r in selected if r["_dietary_flags"]["is_gluten_free"])

    if vegan_count < MIN_VEGAN:
        needed = MIN_VEGAN - vegan_count
        pool = sorted(
            [r for r in recipes if r["_dietary_flags"]["is_vegan"] and r["title"].lower() not in seen_titles],
            key=lambda r: r.get("_quality_score", 0), reverse=True
        )
        for r in pool[:needed]:
            add_recipe(r)

    veg_count = sum(1 for r in selected if r["_dietary_flags"]["is_vegetarian"])
    if veg_count < MIN_VEGETARIAN:
        needed = MIN_VEGETARIAN - veg_count
        pool = sorted(
            [r for r in recipes if r["_dietary_flags"]["is_vegetarian"] and r["title"].lower() not in seen_titles],
            key=lambda r: r.get("_quality_score", 0), reverse=True
        )
        for r in pool[:needed]:
            add_recipe(r)

    gf_count = sum(1 for r in selected if r["_dietary_flags"]["is_gluten_free"])
    if gf_count < MIN_GLUTEN_FREE:
        needed = MIN_GLUTEN_FREE - gf_count
        pool = sorted(
            [r for r in recipes if r["_dietary_flags"]["is_gluten_free"] and r["title"].lower() not in seen_titles],
            key=lambda r: r.get("_quality_score", 0), reverse=True
        )
        for r in pool[:needed]:
            add_recipe(r)

    # Phase 3: Fill to target
    remaining = sorted(
        [r for r in recipes if r["title"].lower() not in seen_titles],
        key=lambda r: r.get("_quality_score", 0), reverse=True
    )
    for r in remaining:
        if len(selected) >= TARGET_TOTAL:
            break
        add_recipe(r)

    # Trim if over target
    selected = selected[:TARGET_TOTAL]

    # Stats
    final_cuisine = Counter(r.get("_cuisine", "Other") for r in selected)
    final_vegan = sum(1 for r in selected if r["_dietary_flags"]["is_vegan"])
    final_veg = sum(1 for r in selected if r["_dietary_flags"]["is_vegetarian"])
    final_gf = sum(1 for r in selected if r["_dietary_flags"]["is_gluten_free"])

    logger.info("\n=== Final Subset (%d recipes) ===", len(selected))
    logger.info("Vegan: %d (target ≥%d)", final_vegan, MIN_VEGAN)
    logger.info("Vegetarian: %d (target ≥%d)", final_veg, MIN_VEGETARIAN)
    logger.info("Gluten-free: %d (target ≥%d)", final_gf, MIN_GLUTEN_FREE)
    logger.info("Cuisines:")
    for cuisine, count in final_cuisine.most_common():
        logger.info("  %20s: %4d (%5.1f%%)", cuisine, count, count / len(selected) * 100)

    return selected


def save_subset(recipes: list[dict], path: str) -> None:
    """Save subset to JSONL."""
    with open(path, "w", encoding="utf-8") as f:
        for recipe in recipes:
            output = {
                "title": recipe["title"],
                "ingredients": recipe.get("ingredients", []),
                "directions": recipe.get("directions", []),
                "NER": recipe.get("NER", []),
                "link": recipe.get("link", ""),
                "source": recipe.get("source", ""),
                "_cuisine": recipe.get("_cuisine", "Other"),
                "_dietary_flags": recipe.get("_dietary_flags", {}),
                "_dietary_tags": recipe.get("_dietary_tags", []),
                "_quality_score": round(recipe.get("_quality_score", 0), 3),
            }
            f.write(json.dumps(output, ensure_ascii=False) + "\n")
    logger.info("Saved %d recipes to %s", len(recipes), path)


def main():
    random.seed(42)

    # Step 1: Load
    recipes = load_recipes(INPUT_PATH)

    # Step 2: Dietary inference
    logger.info("Applying dietary inference...")
    recipes = apply_dietary_flags(recipes)

    vegan_count = sum(1 for r in recipes if r["_dietary_flags"]["is_vegan"])
    veg_count = sum(1 for r in recipes if r["_dietary_flags"]["is_vegetarian"])
    gf_count = sum(1 for r in recipes if r["_dietary_flags"]["is_gluten_free"])
    logger.info("Corpus: vegan=%d, vegetarian=%d, gluten-free=%d", vegan_count, veg_count, gf_count)

    # Step 3: Cuisine classification (heuristic)
    logger.info("Classifying cuisines (keyword heuristic)...")
    for recipe in recipes:
        recipe["_cuisine"] = classify_cuisine_heuristic(recipe)

    cuisine_dist = Counter(r["_cuisine"] for r in recipes)
    logger.info("Heuristic cuisine distribution:")
    for cuisine, count in cuisine_dist.most_common():
        logger.info("  %20s: %d (%.1f%%)", cuisine, count, count / len(recipes) * 100)

    # Step 4: Quality scoring
    logger.info("Scoring recipe quality...")
    for recipe in recipes:
        recipe["_quality_score"] = score_recipe_quality(recipe)

    # Step 5: Balanced selection
    subset = select_balanced_subset(recipes)

    # Step 6: Save
    save_subset(subset, OUTPUT_PATH)
    logger.info("Done!")


if __name__ == "__main__":
    main()
