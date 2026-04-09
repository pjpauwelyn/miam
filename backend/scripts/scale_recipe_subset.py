#!/usr/bin/env python3
"""
scale_recipe_subset.py — Select additional recipes from the 58K unused pool
to fill cuisine, course, dietary, and time-range gaps.

Current state: 2,000 enriched recipes with heavy American bias (612/2000),
weak coverage of Thai (15), Vietnamese (4), Turkish (5), Moroccan (3),
Peruvian (7), Korean (29), Lebanese (21), Caribbean (17), African (23),
Middle Eastern (25). Also low on: starters, soups, breakfasts, salads,
vegan, quick (<15min), and slow (>120min) recipes.

Strategy:
1. Load 58K unused RecipeNLG records (excluding already-enriched titles)
2. Run keyword cuisine + dietary inference on all
3. Prioritise selection to fill gaps:
   - First pass: fill underrepresented cuisines to quota
   - Second pass: fill underrepresented courses
   - Third pass: fill dietary gaps (vegan, pescatarian)
   - Fourth pass: fill time-range gaps (quick, slow-cook)
   - Final pass: top up with quality-scored recipes, avoiding American overload
4. Deduplicate against existing 2,000
5. Output JSONL ready for enrichment

Target: 3,000 additional recipes → total 5,000

Usage:
    cd backend && python ../scripts/scale_recipe_subset.py
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
import sys
from collections import Counter, defaultdict

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, BACKEND_DIR)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "open")
INPUT_PATH = os.path.join(DATA_DIR, "recipenlg_filtered.jsonl")
EXISTING_PATH = os.path.join(DATA_DIR, "recipenlg_enriched_2000.jsonl")
OUTPUT_PATH = os.path.join(DATA_DIR, "recipenlg_subset_additional_3000.jsonl")

TARGET_ADDITIONAL = 3000

random.seed(42)

# -----------------------------------------------------------------------
# Cuisine keyword heuristic (expanded from original)
# -----------------------------------------------------------------------
CUISINE_KEYWORDS: dict[str, list[str]] = {
    "Italian": [
        "parmesan", "parmigiano", "mozzarella", "ricotta", "mascarpone",
        "basil", "oregano", "prosciutto", "pancetta", "penne", "spaghetti",
        "linguine", "fettuccine", "lasagna", "lasagne", "risotto", "gnocchi",
        "ravioli", "tortellini", "focaccia", "ciabatta", "bruschetta",
        "antipasto", "pesto", "marinara", "bolognese", "carbonara",
        "tiramisu", "cannoli", "polenta", "arancini", "ossobuco",
    ],
    "French": [
        "beurre", "gruyère", "gruyere", "camembert", "brie", "roquefort",
        "dijon", "croissant", "baguette", "ratatouille", "bouillabaisse",
        "coq au vin", "crème", "soufflé", "souffle", "quiche", "crêpe",
        "crepe", "béarnaise", "bearnaise", "béchamel", "bechamel",
        "confit", "cassoulet", "tarte", "flambé", "flambe", "blanquette",
        "dauphinois", "gratin", "brioche", "madeleines", "profiteroles",
        "choux", "bourguignon", "provençal", "provencal", "niçoise", "nicoise",
    ],
    "Spanish": [
        "chorizo", "manchego", "paprika", "saffron", "paella", "tapas",
        "gazpacho", "tortilla española", "patatas bravas", "croquetas",
        "jamón", "jamon", "piquillo", "romesco", "aioli", "sofrito",
        "churros", "flan", "sangria", "pimiento", "morcilla",
    ],
    "Greek": [
        "feta", "halloumi", "tzatziki", "moussaka", "souvlaki", "gyros",
        "spanakopita", "dolma", "dolmades", "baklava", "phyllo", "filo",
        "kalamata", "ouzo", "pita", "hummus", "tahini", "orzo",
    ],
    "Moroccan": [
        "tagine", "tajine", "harissa", "ras el hanout", "couscous",
        "preserved lemon", "chermoula", "pastilla", "bastilla", "zaalouk",
        "msemmen", "mint tea", "argan", "merguez", "rfissa",
        "moroccan", "marrakech",
    ],
    "Lebanese": [
        "tabouleh", "tabbouleh", "kibbeh", "fattoush", "labneh",
        "za'atar", "zaatar", "sumac", "toum", "shawarma", "manoushe",
        "manakish", "kafta", "kofta", "lebanese", "beirut",
        "baba ghanoush", "baba ganoush",
    ],
    "Turkish": [
        "köfte", "kofte", "börek", "borek", "pide", "lahmacun",
        "baklava", "dolma", "ayran", "iskender", "adana", "turkish",
        "imam bayildi", "menemen", "simit", "gözleme", "gozleme",
        "manti", "lokum", "çiğ köfte", "cacik", "sucuk",
    ],
    "Indian": [
        "turmeric", "garam masala", "curry", "masala", "paneer",
        "naan", "tandoori", "biryani", "dal", "daal", "dhal",
        "samosa", "chutney", "raita", "tikka", "korma", "vindaloo",
        "rogan josh", "ghee", "chapati", "roti", "cardamom",
        "coriander", "cumin", "fenugreek", "tamarind", "naan",
    ],
    "Chinese": [
        "soy sauce", "hoisin", "tofu", "bok choy", "pak choi",
        "wonton", "dim sum", "dumpling", "kung pao", "szechuan",
        "sichuan", "wok", "stir fry", "stir-fry", "five spice",
        "oyster sauce", "sesame oil", "chow mein", "lo mein",
        "mapo tofu", "char siu", "spring roll", "egg roll",
        "sweet and sour", "general tso", "fried rice",
    ],
    "Japanese": [
        "miso", "sake", "mirin", "dashi", "wasabi", "sushi",
        "sashimi", "tempura", "ramen", "udon", "soba", "teriyaki",
        "edamame", "tofu", "nori", "matcha", "ponzu", "katsu",
        "tonkatsu", "gyoza", "onigiri", "bento", "yakitori",
        "okonomiyaki", "takoyaki", "mochi",
    ],
    "Korean": [
        "kimchi", "gochujang", "gochugaru", "bulgogi", "bibimbap",
        "japchae", "tteokbokki", "soju", "doenjang", "ssam",
        "korean", "kimbap", "mandoo", "mandu", "banchan",
        "galbi", "kalbi", "sundubu", "jjigae", "pajeon",
        "hotteok", "bingsu",
    ],
    "Thai": [
        "thai basil", "lemongrass", "galangal", "kaffir lime",
        "fish sauce", "pad thai", "green curry", "red curry",
        "coconut milk", "thai", "tom yum", "tom kha", "massaman",
        "panang", "satay", "som tam", "pad kra pao", "larb",
        "sticky rice", "nam prik", "holy basil",
    ],
    "Vietnamese": [
        "pho", "banh mi", "fish sauce", "nuoc mam", "nuoc cham",
        "rice paper", "spring roll", "vietnamese", "lemongrass",
        "sriracha", "bun", "bun cha", "goi cuon", "cao lau",
        "banh xeo", "che", "com tam",
    ],
    "Mexican": [
        "tortilla", "cilantro", "jalapeño", "jalapeno", "chipotle",
        "guacamole", "enchilada", "burrito", "taco", "quesadilla",
        "mole", "salsa verde", "pico de gallo", "queso", "tamale",
        "pozole", "carnitas", "al pastor", "churros", "tres leches",
        "elote", "esquites", "chiles rellenos",
    ],
    "Peruvian": [
        "ceviche", "aji", "lomo saltado", "anticucho", "peruvian",
        "papa a la huancaina", "causa", "rocoto", "lucuma",
        "chicha", "cuy", "quinoa", "amarillo",
    ],
    "Middle Eastern": [
        "sumac", "za'atar", "zaatar", "tahini", "hummus", "falafel",
        "pita", "flatbread", "pomegranate", "middle eastern",
        "shawarma", "fattoush", "musakhan", "kibbeh", "freekeh",
        "muhammara", "maqluba", "fatteh",
    ],
    "African": [
        "injera", "berbere", "jollof", "fufu", "egusi",
        "suya", "biltong", "bobotie", "chakalaka",
        "african", "peri peri", "piri piri", "plantain",
        "yam", "cassava", "okra", "groundnut",
    ],
    "Caribbean": [
        "jerk", "plantain", "scotch bonnet", "allspice",
        "caribbean", "jamaican", "rice and peas", "callaloo",
        "ackee", "saltfish", "roti", "doubles", "pelau",
        "sorrel", "rum cake", "conch",
    ],
    "British": [
        "shepherd's pie", "shepherds pie", "fish and chips", "bangers",
        "yorkshire pudding", "cornish pasty", "scones", "crumpets",
        "marmite", "treacle", "sticky toffee", "spotted dick",
        "toad in the hole", "ploughman", "steak and kidney",
        "worcestershire", "cheddar", "stilton", "clotted cream",
        "full english", "bubble and squeak", "eton mess",
    ],
    "German": [
        "sauerkraut", "schnitzel", "bratwurst", "pretzel",
        "strudel", "spaetzle", "spätzle", "knödel", "knodel",
        "currywurst", "kartoffelsalat", "rouladen", "sauerbraten",
        "schwarzwälder", "schwarzwalder", "lebkuchen", "dampfnudel",
        "flammkuchen", "maultaschen",
    ],
    "Scandinavian": [
        "gravlax", "smörgåsbord", "smorgasbord", "lingonberry",
        "dill", "cardamom buns", "kanelbullar", "lutefisk",
        "frikadeller", "smørrebrød", "smorrebrod", "rugbrød",
        "scandinavian", "swedish", "norwegian", "danish", "finnish",
        "janssons", "köttbullar", "kottbullar", "aquavit",
    ],
    "Dutch": [
        "stroopwafel", "bitterballen", "stamppot", "erwtensoep",
        "poffertjes", "pannenkoeken", "hutspot", "kroket",
        "dutch", "gouda", "edam", "speculaas", "oliebollen",
        "hachee", "boerenkool",
    ],
}

# Course keyword heuristic
COURSE_KEYWORDS: dict[str, list[str]] = {
    "breakfast": [
        "breakfast", "pancake", "waffle", "omelette", "omelet",
        "scrambled egg", "french toast", "granola", "porridge",
        "smoothie bowl", "eggs benedict", "hash brown", "muesli",
    ],
    "soup": [
        "soup", "chowder", "bisque", "broth", "stew", "minestrone",
        "gazpacho", "consommé", "consomme", "potage", "goulash",
    ],
    "salad": [
        "salad", "slaw", "coleslaw", "tabbouleh", "fattoush",
        "caesar", "niçoise", "nicoise", "waldorf", "cobb",
    ],
    "starter": [
        "appetizer", "appetiser", "starter", "bruschetta", "crostini",
        "spring roll", "samosa", "arancini", "ceviche", "tartare",
        "canapé", "canape",
    ],
    "dessert": [
        "dessert", "cake", "cookie", "brownie", "pie", "tart",
        "pudding", "mousse", "ice cream", "sorbet", "crumble",
        "cheesecake", "tiramisu", "pavlova", "soufflé", "souffle",
        "truffle", "macaron", "fudge", "meringue",
    ],
    "snack": [
        "snack", "dip", "chips", "crackers", "energy ball",
        "granola bar", "hummus", "guacamole", "popcorn", "trail mix",
        "muffin", "scone",
    ],
    "side": [
        "side dish", "side salad", "coleslaw", "fries", "mashed",
        "roasted vegetables", "grilled vegetables", "rice pilaf",
        "garlic bread", "cornbread",
    ],
}

# Quick recipe indicators (likely <15 min total)
QUICK_KEYWORDS = [
    "5 minute", "5-minute", "10 minute", "10-minute", "no cook",
    "no-cook", "raw", "smoothie", "quick", "instant", "microwave",
    "5-min", "10-min", "easy",
]

# Slow-cook indicators (likely >120 min total)
SLOW_KEYWORDS = [
    "slow cook", "slow-cook", "braise", "braised", "overnight",
    "48 hour", "24 hour", "low and slow", "pot roast", "pulled",
    "smoked", "crock pot", "crockpot", "slow cooker",
]


def classify_cuisine(raw: dict) -> str:
    """Classify cuisine via keyword heuristic on title + NER."""
    title_lower = raw.get("title", "").lower()
    ner_lower = " ".join(n.lower() for n in raw.get("NER", []))
    combined = f"{title_lower} {ner_lower}"

    scores: dict[str, int] = {}
    for cuisine, keywords in CUISINE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in combined)
        if score > 0:
            scores[cuisine] = score

    if not scores:
        return "Unknown"
    return max(scores, key=scores.get)


def classify_course(raw: dict) -> str:
    """Classify course via keyword heuristic on title."""
    title_lower = raw.get("title", "").lower()
    for course, keywords in COURSE_KEYWORDS.items():
        for kw in keywords:
            if kw in title_lower:
                return course
    return "main"  # Default


def is_quick(raw: dict) -> bool:
    title_lower = raw.get("title", "").lower()
    return any(kw in title_lower for kw in QUICK_KEYWORDS)


def is_slow(raw: dict) -> bool:
    title_lower = raw.get("title", "").lower()
    return any(kw in title_lower for kw in SLOW_KEYWORDS)


def compute_quality_score(raw: dict) -> float:
    """Quality score based on field completeness."""
    score = 1.0
    ner = raw.get("NER", [])
    dirs = raw.get("directions", [])
    if len(ner) < 5:
        score -= 0.1
    if len(ner) < 3:
        score -= 0.2
    if len(dirs) < 3:
        score -= 0.15
    if len(dirs) < 2:
        score -= 0.2
    title = raw.get("title", "")
    if len(title) < 5:
        score -= 0.1
    if any(c.isdigit() for c in title):
        score -= 0.05  # Titles like "Recipe #482"
    return max(0.0, score)


def main():
    # Step 1: Load existing enriched titles to exclude
    logger.info("Loading existing enriched titles...")
    existing_titles: set[str] = set()
    with open(EXISTING_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                existing_titles.add(json.loads(line)["title"].strip().lower())
    logger.info("Excluding %d already-enriched titles", len(existing_titles))

    # Step 2: Load and classify all unused recipes
    logger.info("Loading and classifying unused recipes...")

    # Fast vegan/vegetarian check via keyword lists (avoids 200s dietary engine)
    MEAT_TERMS = {
        "chicken", "beef", "pork", "lamb", "turkey", "duck", "veal", "venison",
        "bacon", "ham", "sausage", "prosciutto", "pancetta", "salami", "pepperoni",
        "steak", "mince", "ground beef", "ground pork", "ground turkey",
        "ribs", "brisket", "chorizo", "meatball", "meat",
    }
    FISH_TERMS = {
        "salmon", "tuna", "cod", "shrimp", "prawn", "lobster", "crab",
        "fish", "anchovy", "sardine", "mackerel", "trout", "halibut",
        "scallop", "mussel", "clam", "oyster", "squid", "octopus", "calamari",
    }
    DAIRY_TERMS = {
        "milk", "cheese", "butter", "cream", "yogurt", "yoghurt",
        "sour cream", "cream cheese", "parmesan", "mozzarella", "cheddar",
        "ricotta", "mascarpone", "ghee", "whey",
    }
    EGG_TERMS = {"egg", "eggs", "yolk", "egg white"}

    def fast_dietary(ner: list[str]) -> tuple[bool, bool]:
        """Fast vegan/vegetarian check. Returns (is_vegan, is_vegetarian)."""
        lower_ner = {n.lower().strip() for n in ner}
        combined = " ".join(lower_ner)
        has_meat = any(t in combined for t in MEAT_TERMS)
        has_fish = any(t in combined for t in FISH_TERMS)
        has_dairy = any(t in combined for t in DAIRY_TERMS)
        has_egg = any(t in combined for t in EGG_TERMS)
        is_vegetarian = not has_meat and not has_fish
        is_vegan = is_vegetarian and not has_dairy and not has_egg
        return is_vegan, is_vegetarian

    all_recipes: list[dict] = []
    skipped_existing = 0
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            raw = json.loads(line)
            if raw["title"].strip().lower() in existing_titles:
                skipped_existing += 1
                continue

            # Classify
            cuisine = classify_cuisine(raw)
            course = classify_course(raw)
            ner = raw.get("NER", [])
            is_vegan, is_vegetarian = fast_dietary(ner)
            quality = compute_quality_score(raw)

            raw["_heuristic_cuisine"] = cuisine
            raw["_heuristic_course"] = course
            raw["_is_vegan"] = is_vegan
            raw["_is_vegetarian"] = is_vegetarian
            raw["_is_gluten_free"] = False  # Determined during enrichment
            raw["_is_pescatarian"] = not any(t in " ".join(n.lower() for n in ner) for t in MEAT_TERMS)
            raw["_is_quick"] = is_quick(raw)
            raw["_is_slow"] = is_slow(raw)
            raw["_quality"] = quality
            all_recipes.append(raw)

    logger.info(
        "Loaded %d unused recipes (skipped %d existing)",
        len(all_recipes), skipped_existing,
    )

    # Sort by quality descending for all passes
    all_recipes.sort(key=lambda r: r["_quality"], reverse=True)

    # Step 3: Index recipes by cuisine, course, dietary, time
    by_cuisine: dict[str, list[dict]] = defaultdict(list)
    by_course: dict[str, list[dict]] = defaultdict(list)
    vegan_pool: list[dict] = []
    quick_pool: list[dict] = []
    slow_pool: list[dict] = []

    for r in all_recipes:
        by_cuisine[r["_heuristic_cuisine"]].append(r)
        by_course[r["_heuristic_course"]].append(r)
        if r["_is_vegan"]:
            vegan_pool.append(r)
        if r["_is_quick"]:
            quick_pool.append(r)
        if r["_is_slow"]:
            slow_pool.append(r)

    logger.info("Cuisine pool sizes: %s",
                {k: len(v) for k, v in sorted(by_cuisine.items(), key=lambda x: -len(x[1]))})

    # Step 4: Priority selection
    selected: list[dict] = []
    selected_titles: set[str] = set()

    def add_recipe(r: dict) -> bool:
        t = r["title"].strip().lower()
        if t in selected_titles:
            return False
        selected_titles.add(t)
        selected.append(r)
        return True

    # --- Pass 1: Fill cuisine gaps ---
    # Current counts (from existing 2,000)
    current_cuisine_counts = {
        "Italian": 199, "French": 99, "Spanish": 70, "Greek": 48,
        "Moroccan": 3, "Lebanese": 21, "Turkish": 5, "Indian": 57,
        "Chinese": 94, "Japanese": 110, "Korean": 29, "Thai": 15,
        "Vietnamese": 4, "Mexican": 146, "Peruvian": 7, "American": 612,
        "British": 49, "German": 59, "Scandinavian": 40,
        "Middle Eastern": 25, "African": 23, "Caribbean": 17,
        "Fusion": 69, "Other": 199, "Dutch": 0,
    }

    # Targets: EU/key cuisines get higher targets
    cuisine_targets = {
        "Italian": 350, "French": 350, "Spanish": 200, "Greek": 200,
        "Moroccan": 120, "Lebanese": 120, "Turkish": 120, "Indian": 300,
        "Chinese": 250, "Japanese": 250, "Korean": 150, "Thai": 200,
        "Vietnamese": 100, "Mexican": 250, "Peruvian": 50, "American": 650,
        "British": 150, "German": 150, "Dutch": 80, "Scandinavian": 100,
        "Middle Eastern": 150, "African": 100, "Caribbean": 80,
        "Fusion": 100, "Other": 200,
    }

    logger.info("Pass 1: Filling cuisine gaps...")
    # Sort cuisines by gap size (largest gap first)
    cuisine_priority = sorted(
        cuisine_targets.items(),
        key=lambda x: -(x[1] - current_cuisine_counts.get(x[0], 0)),
    )

    for cuisine, target in cuisine_priority:
        current = current_cuisine_counts.get(cuisine, 0)
        need = max(0, target - current)
        if need == 0:
            continue
        pool = by_cuisine.get(cuisine, [])
        added = 0
        for r in pool:
            if added >= need:
                break
            if add_recipe(r):
                added += 1
        logger.info("  %s: needed %d, added %d (pool size %d)",
                    cuisine, need, added, len(pool))

    logger.info("After Pass 1: %d selected", len(selected))

    # --- Pass 2: Fill course gaps ---
    current_course_counts = {
        "main": 1264, "dessert": 262, "side": 237, "snack": 122,
        "salad": 76, "breakfast": 74, "starter": 64, "soup": 61,
    }
    course_targets = {
        "main": 2500, "dessert": 500, "side": 400, "snack": 200,
        "salad": 200, "breakfast": 250, "starter": 200, "soup": 200,
    }

    logger.info("Pass 2: Filling course gaps...")
    for course in ["breakfast", "soup", "starter", "salad", "snack", "side", "dessert"]:
        current = current_course_counts.get(course, 0)
        target = course_targets.get(course, 100)
        need = max(0, target - current)
        pool = by_course.get(course, [])
        added = 0
        for r in pool:
            if added >= need:
                break
            if add_recipe(r):
                added += 1
        logger.info("  %s: needed %d, added %d", course, need, added)

    logger.info("After Pass 2: %d selected", len(selected))

    # --- Pass 3: Fill dietary gaps ---
    logger.info("Pass 3: Filling dietary gaps (vegan)...")
    current_vegan = 249
    vegan_target = 500
    vegan_need = max(0, vegan_target - current_vegan)
    added_vegan = 0
    for r in vegan_pool:
        if added_vegan >= vegan_need:
            break
        if add_recipe(r):
            added_vegan += 1
    logger.info("  Vegan: needed %d, added %d", vegan_need, added_vegan)

    logger.info("After Pass 3: %d selected", len(selected))

    # --- Pass 4: Fill time-range gaps ---
    logger.info("Pass 4: Filling time-range gaps...")
    quick_need = max(0, 150 - 31)  # Target 150 quick recipes
    added_quick = 0
    for r in quick_pool:
        if added_quick >= quick_need:
            break
        if add_recipe(r):
            added_quick += 1
    logger.info("  Quick (<15min): needed %d, added %d", quick_need, added_quick)

    slow_need = max(0, 200 - 87)  # Target 200 slow recipes
    added_slow = 0
    for r in slow_pool:
        if added_slow >= slow_need:
            break
        if add_recipe(r):
            added_slow += 1
    logger.info("  Slow (>120min): needed %d, added %d", slow_need, added_slow)

    logger.info("After Pass 4: %d selected", len(selected))

    # --- Pass 5: Top up to target (avoid American overload) ---
    logger.info("Pass 5: Top up to %d...", TARGET_ADDITIONAL)
    remaining_needed = TARGET_ADDITIONAL - len(selected)
    if remaining_needed > 0:
        # Use recipes not classified as American, sorted by quality
        non_american = [
            r for r in all_recipes
            if r["_heuristic_cuisine"] != "American"
            and r["title"].strip().lower() not in selected_titles
        ]
        random.shuffle(non_american)
        added_topup = 0
        for r in non_american:
            if added_topup >= remaining_needed:
                break
            if add_recipe(r):
                added_topup += 1
        logger.info("  Top-up (non-American): added %d", added_topup)

    # If still short, add from Unknown/American
    remaining_needed = TARGET_ADDITIONAL - len(selected)
    if remaining_needed > 0:
        leftover = [
            r for r in all_recipes
            if r["title"].strip().lower() not in selected_titles
        ]
        random.shuffle(leftover)
        added_final = 0
        for r in leftover:
            if added_final >= remaining_needed:
                break
            if add_recipe(r):
                added_final += 1
        logger.info("  Final top-up: added %d", added_final)

    logger.info("Total selected: %d", len(selected))

    # Step 5: Print distribution stats
    final_cuisine = Counter(r["_heuristic_cuisine"] for r in selected)
    final_course = Counter(r["_heuristic_course"] for r in selected)
    final_vegan = sum(1 for r in selected if r["_is_vegan"])
    final_vegetarian = sum(1 for r in selected if r["_is_vegetarian"])
    final_quick = sum(1 for r in selected if r["_is_quick"])
    final_slow = sum(1 for r in selected if r["_is_slow"])

    logger.info("=== SELECTION STATS (additional 3,000) ===")
    logger.info("Cuisine distribution:")
    for c, n in final_cuisine.most_common():
        existing = current_cuisine_counts.get(c, 0)
        logger.info("  %s: %d new + %d existing = %d total", c, n, existing, n + existing)
    logger.info("Course distribution:")
    for c, n in final_course.most_common():
        existing = current_course_counts.get(c, 0)
        logger.info("  %s: %d new + %d existing = %d total", c, n, existing, n + existing)
    logger.info("Dietary: vegan=%d, vegetarian=%d", final_vegan, final_vegetarian)
    logger.info("Time: quick=%d, slow=%d", final_quick, final_slow)

    # Step 6: Save
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for r in selected:
            # Strip internal classification keys before saving
            clean = {k: v for k, v in r.items() if not k.startswith("_")}
            f.write(json.dumps(clean, ensure_ascii=False) + "\n")

    logger.info("Saved %d recipes to %s", len(selected), OUTPUT_PATH)


if __name__ == "__main__":
    main()
