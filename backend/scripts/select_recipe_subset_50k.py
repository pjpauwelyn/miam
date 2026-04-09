#!/usr/bin/env python3
"""
select_recipe_subset_50k.py — Select a balanced 50,000-recipe subset from
a full RecipeNLG extraction (JSONL produced by extract_recipenlg.py).

Strategy
--------
1. Stream the full extracted JSONL (no RAM spike for large files)
2. Apply keyword-based cuisine heuristic (same logic as select_recipe_subset.py)
3. Score each recipe for quality
4. Select up to TARGET_TOTAL recipes balanced across:
   - Cuisines (target % per cuisine)
   - Dietary types (vegan / vegetarian / gluten-free minimums)
5. Write recipenlg_subset_50k.jsonl

No API keys or backend imports required — runs standalone with Python 3.10+.

Usage (from repo root OR from anywhere):
    python backend/scripts/select_recipe_subset_50k.py \\
        --input  /path/to/recipenlg_extracted_full.jsonl \\
        --output /path/to/recipenlg_subset_50k.jsonl
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
from collections import Counter, defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── tunables ──────────────────────────────────────────────────────────────────

TARGET_TOTAL = 50_000

MIN_VEGAN        = 5_000
MIN_VEGETARIAN   = 8_000   # includes vegan
MIN_GLUTEN_FREE  = 2_500

# ── cuisine keywords (identical to select_recipe_subset.py) ──────────────────

CUISINE_KEYWORDS: dict[str, list[str]] = {
    "Italian": [
        "parmesan","parmigiano","mozzarella","ricotta","mascarpone",
        "basil","oregano","prosciutto","pancetta","penne","spaghetti",
        "linguine","fettuccine","lasagna","lasagne","risotto","gnocchi",
        "ravioli","tortellini","focaccia","ciabatta","bruschetta",
        "marinara","bolognese","carbonara","pesto","tiramisu",
        "antipasto","polenta","arancini","osso buco",
    ],
    "French": [
        "dijon","brie","camembert","gruyère","gruyere","roquefort",
        "crème fraîche","creme fraiche","bechamel","béchamel",
        "ratatouille","coq au vin","bouillabaisse","soufflé","souffle",
        "crêpe","crepe","croissant","baguette","brioche","quiche",
        "cassoulet","confit","meunière","provençal","provencal",
        "herbes de provence","tarragon","chervil","béarnaise",
    ],
    "Spanish": [
        "chorizo","saffron","paprika","manchego","paella","gazpacho",
        "tapas","patatas bravas","tortilla española","churros",
        "sangria","sobrassada","pimiento","romesco",
    ],
    "Greek": [
        "feta","kalamata","tzatziki","moussaka","spanakopita",
        "souvlaki","gyro","phyllo","filo","halloumi",
        "dolma","oregano","olive",
    ],
    "Indian": [
        "curry","turmeric","cumin","garam masala","cardamom",
        "coriander","cilantro","naan","paneer","ghee","chutney",
        "biryani","tikka","masala","tandoori","dal","dhal",
        "samosa","chapati","roti","raita","korma","vindaloo",
        "tamarind","fenugreek","mustard seed",
    ],
    "Chinese": [
        "soy sauce","hoisin","oyster sauce","sesame oil","five spice",
        "star anise","szechuan","sichuan","wonton","dim sum",
        "lo mein","chow mein","kung pao","mapo","stir fry",
        "bok choy","tofu","bean sprout","water chestnut",
        "bamboo shoot","rice wine","doubanjiang",
    ],
    "Japanese": [
        "miso","dashi","nori","wasabi","sake","mirin",
        "sushi","sashimi","tempura","ramen","udon","soba",
        "teriyaki","ponzu","edamame","tofu","panko",
        "katsu","mochi","matcha","bonito",
    ],
    "Thai": [
        "fish sauce","lemongrass","galangal","kaffir lime",
        "thai basil","coconut milk","pad thai","green curry",
        "red curry","massaman","satay","tom yum","tom kha",
        "sriracha","bird eye chili","palm sugar",
    ],
    "Mexican": [
        "tortilla","salsa","jalapeño","jalapeno","chipotle",
        "cumin","enchilada","taco","burrito","quesadilla",
        "guacamole","avocado","cilantro","lime","black bean",
        "refried bean","tamale","mole","pozole","chili powder",
        "ancho","poblano","queso",
    ],
    "Korean": [
        "gochujang","gochugaru","kimchi","sesame","doenjang",
        "bibimbap","bulgogi","japchae","tteok","soju",
        "korean","banchan","ssam",
    ],
    "Vietnamese": [
        "fish sauce","lemongrass","pho","banh mi","spring roll",
        "rice paper","vietnamese","nuoc mam","nuoc cham",
    ],
    "Turkish": [
        "sumac","pomegranate","turkish","lahmacun","pide",
        "börek","borek","baklava","kebab","kofte",
        "yoghurt","bulgur","za'atar",
    ],
    "Middle Eastern": [
        "tahini","hummus","za'atar","zaatar","sumac",
        "pomegranate","chickpea","flatbread","falafel",
        "shawarma","baba ghanoush","harissa","preserved lemon",
        "rose water","pistachio",
    ],
    "Moroccan": [
        "harissa","ras el hanout","preserved lemon","tagine",
        "couscous","moroccan","merguez","argan",
    ],
    "Lebanese": [
        "tabbouleh","fattoush","kibbeh","labneh","lebanese",
        "za'atar","sumac","pomegranate molasses",
    ],
    "British": [
        "worcestershire","marmite","stilton","cheddar",
        "shepherd's pie","fish and chips","trifle","scone",
        "clotted cream","yorkshire pudding","spotted dick",
        "bangers","crumpet",
    ],
    "German": [
        "sauerkraut","bratwurst","pretzel","schnitzel",
        "strudel","spätzle","spaetzle","pumpernickel","german",
    ],
    "Scandinavian": [
        "dill","lingonberry","cardamom","gravlax","smørrebrød",
        "swedish","norwegian","danish","finnish",
        "meatball","pickled herring",
    ],
    "Caribbean": [
        "jerk","allspice","plantain","scotch bonnet",
        "caribbean","jamaican","coconut",
    ],
    "American": [
        "ranch","buffalo","bbq","barbecue","cornbread",
        "mac and cheese","chili con carne","coleslaw",
        "thanksgiving","brownie","cookie","pancake",
    ],
    "Peruvian": [
        "aji amarillo","ceviche","peruvian","quinoa",
        "purple corn","lucuma",
    ],
    "African": [
        "berbere","injera","fufu","jollof","african",
        "piri piri","peri peri",
    ],
}

TITLE_CUISINE_KEYWORDS: dict[str, list[str]] = {
    "Italian":       ["italian","pasta","risotto","pizza","lasagna","lasagne","gnocchi",
                      "bruschetta","minestrone","panna cotta","tiramisu","carbonara",
                      "bolognese","primavera","alfredo","puttanesca","arrabbiata"],
    "French":        ["french","provençal","provencal","gratin","quiche","crêpe","crepe",
                      "soufflé","souffle","ratatouille","cassoulet","bouillabaisse"],
    "Indian":        ["indian","curry","tikka","masala","biryani","tandoori","korma",
                      "vindaloo","dal","dhal","samosa","naan"],
    "Chinese":       ["chinese","stir fry","stir-fry","lo mein","chow mein","kung pao",
                      "sweet and sour","fried rice","dim sum","wonton","dumpling"],
    "Japanese":      ["japanese","sushi","sashimi","tempura","ramen","teriyaki",
                      "miso","udon","soba","katsu","mochi","matcha"],
    "Thai":          ["thai","pad thai","green curry","red curry","tom yum","tom kha",
                      "massaman","satay"],
    "Mexican":       ["mexican","taco","burrito","enchilada","quesadilla","fajita",
                      "chimichanga","tamale","mole","pozole","tostada","nachos"],
    "Korean":        ["korean","kimchi","bibimbap","bulgogi","japchae"],
    "Vietnamese":    ["vietnamese","pho","banh mi","spring roll"],
    "Turkish":       ["turkish","kebab","kofte","börek","borek","baklava"],
    "Greek":         ["greek","moussaka","spanakopita","souvlaki","gyro"],
    "Moroccan":      ["moroccan","tagine","couscous"],
    "Middle Eastern":["middle eastern","hummus","falafel","shawarma"],
    "Lebanese":      ["lebanese","tabbouleh","fattoush","kibbeh"],
    "Spanish":       ["spanish","paella","gazpacho","tapas","churros"],
    "British":       ["british","english","fish and chips","shepherd's pie","bangers"],
    "German":        ["german","schnitzel","strudel","pretzel"],
    "Scandinavian":  ["swedish","norwegian","danish","finnish","scandinavian"],
    "Caribbean":     ["caribbean","jamaican","jerk"],
    "American":      ["american","southern","cajun","creole","tex-mex"],
    "Peruvian":      ["peruvian","ceviche"],
    "African":       ["african","ethiopian","nigerian","west african"],
}

TARGET_CUISINE_PCTS: dict[str, float] = {
    "Italian": 0.10, "French": 0.07, "Spanish": 0.04, "Greek": 0.04,
    "Indian": 0.08, "Chinese": 0.07, "Japanese": 0.06, "Thai": 0.05,
    "Mexican": 0.06, "American": 0.09, "British": 0.04, "German": 0.03,
    "Middle Eastern": 0.04, "Korean": 0.03, "Vietnamese": 0.03,
    "Moroccan": 0.02, "Lebanese": 0.02, "Turkish": 0.02,
    "Scandinavian": 0.02, "Caribbean": 0.02, "African": 0.01,
    "Peruvian": 0.01, "Fusion": 0.01, "Other": 0.10,
}

# ── dietary inference (standalone, no backend imports) ────────────────────────

_MEAT = {
    "beef","chicken","pork","lamb","turkey","veal","duck","venison","bison",
    "bacon","ham","sausage","salami","pepperoni","prosciutto","pancetta",
    "lard","gelatin","anchovies","anchovie",
}
_FISH = {
    "salmon","tuna","cod","halibut","tilapia","sardine","herring","mackerel",
    "trout","bass","snapper","mahi","catfish","crab","shrimp","lobster",
    "scallop","oyster","clam","mussel","squid","octopus","fish","seafood",
}
_DAIRY = {
    "milk","butter","cream","cheese","yogurt","yoghurt","ghee","whey",
    "lactose","casein","mozzarella","parmesan","cheddar","brie","feta",
    "ricotta","mascarpone","crème fraîche","creme fraiche","ice cream",
}
_EGGS = {"egg","eggs","mayonnaise","mayo"}
_GLUTEN = {
    "flour","wheat","barley","rye","bread","pasta","noodle","couscous",
    "semolina","bulgur","spelt","kamut","farro","triticale","malt",
    "breadcrumb","panko","soy sauce","beer",
}
_NUTS = {
    "almond","walnut","pecan","cashew","pistachio","hazelnut","macadamia",
    "pine nut","peanut","chestnut","brazil nut","nut","nutmeg",
}
_PORK = {"pork","bacon","ham","lard","prosciutto","pancetta","salami","sausage","pepperoni"}
_SHELLFISH = {"shrimp","crab","lobster","scallop","oyster","clam","mussel","prawn"}
_ALCOHOL = {"wine","beer","rum","vodka","whiskey","whisky","brandy","liqueur","spirits","bourbon","sake","mirin"}


def _infer_dietary(ner: list[str]) -> dict:
    tokens = {n.lower().strip() for n in ner}

    def has_any(group: set) -> bool:
        return any(t in tokens or any(g in t for g in group) for t in tokens
                   for g in group if g in t) or bool(tokens & group)

    has_meat     = has_any(_MEAT)
    has_fish     = has_any(_FISH)
    has_dairy    = has_any(_DAIRY)
    has_eggs     = has_any(_EGGS)
    has_gluten   = has_any(_GLUTEN)
    has_nuts     = has_any(_NUTS)
    has_pork     = has_any(_PORK)
    has_shellfish= has_any(_SHELLFISH)
    has_alcohol  = has_any(_ALCOHOL)

    is_vegan         = not (has_meat or has_fish or has_dairy or has_eggs)
    is_vegetarian    = not (has_meat or has_fish)
    is_pescatarian   = not has_meat
    is_dairy_free    = not has_dairy
    is_gluten_free   = not has_gluten
    is_nut_free      = not has_nuts
    is_halal_ok      = not (has_pork or has_alcohol)

    tags: list[str] = []
    if is_vegan:        tags.append("vegan")
    if is_vegetarian:   tags.append("vegetarian")
    if is_dairy_free:   tags.append("dairy-free")
    if is_gluten_free:  tags.append("gluten-free")
    if is_nut_free:     tags.append("nut-free")
    if is_halal_ok:     tags.append("halal-friendly")
    if is_pescatarian:  tags.append("pescatarian-ok")

    return {
        "flags": {
            "is_vegan": is_vegan, "is_vegetarian": is_vegetarian,
            "is_pescatarian_ok": is_pescatarian, "is_dairy_free": is_dairy_free,
            "is_gluten_free": is_gluten_free, "is_nut_free": is_nut_free,
            "is_halal_ok": is_halal_ok, "contains_pork": has_pork,
            "contains_shellfish": has_shellfish, "contains_alcohol": has_alcohol,
        },
        "tags": tags,
    }

# ── cuisine heuristic ─────────────────────────────────────────────────────────

def _classify_cuisine(recipe: dict) -> str:
    title    = recipe.get("title", "").lower()
    ner_text = " ".join(n.lower() for n in recipe.get("NER", []))
    scores: Counter = Counter()

    for cuisine, keywords in TITLE_CUISINE_KEYWORDS.items():
        for kw in keywords:
            if kw in title:
                scores[cuisine] += 3

    for cuisine, keywords in CUISINE_KEYWORDS.items():
        for kw in keywords:
            if kw in ner_text or kw in title:
                scores[cuisine] += 1

    if not scores:
        return "Other"
    top, score = scores.most_common(1)[0]
    return top if score >= 2 else "Other"

# ── quality scoring ───────────────────────────────────────────────────────────

def _score_quality(recipe: dict) -> float:
    score = 0.0
    ner        = recipe.get("NER", [])
    directions = recipe.get("directions", [])
    title      = recipe.get("title", "")

    n_ing = len(ner)
    if 7 <= n_ing <= 15:   score += 0.30
    elif 5 <= n_ing <= 20: score += 0.20
    else:                  score += 0.10

    n_steps = len(directions)
    if 4 <= n_steps <= 10:   score += 0.20
    elif 3 <= n_steps <= 15: score += 0.15

    if 10 <= len(title) <= 60: score += 0.20
    elif len(title) > 5:       score += 0.10

    unique_ner = {n.lower().strip() for n in ner}
    if len(unique_ner) >= 6:   score += 0.15
    elif len(unique_ner) >= 4: score += 0.10

    if directions:
        avg_len = sum(len(d) for d in directions) / len(directions)
        if avg_len > 50:   score += 0.15
        elif avg_len > 30: score += 0.10

    return min(score, 1.0)

# ── main logic ────────────────────────────────────────────────────────────────

def load_and_annotate(input_path: str) -> list[dict]:
    """Stream JSONL, annotate with cuisine/dietary/quality. Memory-efficient."""
    recipes: list[dict] = []
    with open(input_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            recipe = json.loads(line)
            dietary = _infer_dietary(recipe.get("NER", []))
            recipe["_cuisine"]        = _classify_cuisine(recipe)
            recipe["_dietary_flags"]  = dietary["flags"]
            recipe["_dietary_tags"]   = dietary["tags"]
            recipe["_quality_score"]  = _score_quality(recipe)
            recipes.append(recipe)
            if (i + 1) % 100_000 == 0:
                logger.info("  … loaded & annotated %d recipes", i + 1)
    logger.info("Total loaded: %d", len(recipes))
    return recipes


def select_subset(recipes: list[dict]) -> list[dict]:
    by_cuisine: dict[str, list[dict]] = defaultdict(list)
    for r in recipes:
        by_cuisine[r["_cuisine"]].append(r)

    for c in by_cuisine:
        by_cuisine[c].sort(key=lambda r: r["_quality_score"], reverse=True)

    logger.info("Cuisine distribution in full corpus:")
    for c, rs in sorted(by_cuisine.items(), key=lambda x: -len(x[1])):
        logger.info("  %22s: %6d  (%.1f%%)", c, len(rs), len(rs) / len(recipes) * 100)

    selected: list[dict] = []
    seen: set[str] = set()

    def add(r: dict) -> bool:
        key = r["title"].lower()
        if key not in seen:
            selected.append(r)
            seen.add(key)
            return True
        return False

    # Phase 1 — fill cuisine slots
    for cuisine, pct in TARGET_CUISINE_PCTS.items():
        n_target = max(50, int(TARGET_TOTAL * pct))
        added = 0
        for r in by_cuisine.get(cuisine, []):
            if added >= n_target:
                break
            if add(r):
                added += 1
        logger.info("  Cuisine %-22s  filled %4d / %4d", cuisine, added, n_target)

    # Phase 2 — dietary minimums
    def fill_dietary(flag: str, minimum: int, label: str) -> None:
        current = sum(1 for r in selected if r["_dietary_flags"].get(flag))
        if current >= minimum:
            return
        needed = minimum - current
        pool = sorted(
            [r for r in recipes if r["_dietary_flags"].get(flag) and r["title"].lower() not in seen],
            key=lambda r: r["_quality_score"], reverse=True,
        )
        added = 0
        for r in pool:
            if added >= needed:
                break
            if add(r):
                added += 1
        logger.info("  Dietary %-22s  added %4d to reach minimum %d", label, added, minimum)

    fill_dietary("is_vegan",       MIN_VEGAN,       "vegan")
    fill_dietary("is_vegetarian",  MIN_VEGETARIAN,  "vegetarian")
    fill_dietary("is_gluten_free", MIN_GLUTEN_FREE, "gluten-free")

    # Phase 3 — fill remainder by quality
    remaining = sorted(
        [r for r in recipes if r["title"].lower() not in seen],
        key=lambda r: r["_quality_score"], reverse=True,
    )
    for r in remaining:
        if len(selected) >= TARGET_TOTAL:
            break
        add(r)

    selected = selected[:TARGET_TOTAL]

    # Final stats
    fc = Counter(r["_cuisine"] for r in selected)
    fv  = sum(1 for r in selected if r["_dietary_flags"]["is_vegan"])
    fvg = sum(1 for r in selected if r["_dietary_flags"]["is_vegetarian"])
    fgf = sum(1 for r in selected if r["_dietary_flags"]["is_gluten_free"])
    logger.info("\n=== Final Subset: %d recipes ===", len(selected))
    logger.info("  Vegan:        %5d  (target ≥%d)", fv,  MIN_VEGAN)
    logger.info("  Vegetarian:   %5d  (target ≥%d)", fvg, MIN_VEGETARIAN)
    logger.info("  Gluten-free:  %5d  (target ≥%d)", fgf, MIN_GLUTEN_FREE)
    logger.info("  Cuisines:")
    for c, cnt in fc.most_common():
        logger.info("    %22s: %5d  (%.1f%%)", c, cnt, cnt / len(selected) * 100)

    return selected


def save(recipes: list[dict], output_path: str) -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for r in recipes:
            out = {
                "title":           r["title"],
                "ingredients":     r.get("ingredients", []),
                "directions":      r.get("directions", []),
                "NER":             r.get("NER", []),
                "link":            r.get("link", ""),
                "source":          r.get("source", ""),
                "_cuisine":        r["_cuisine"],
                "_dietary_flags":  r["_dietary_flags"],
                "_dietary_tags":   r["_dietary_tags"],
                "_quality_score":  round(r["_quality_score"], 3),
            }
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
    logger.info("Saved %d recipes → %s", len(recipes), output_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Select a balanced 50k recipe subset")
    parser.add_argument("--input",  "-i", required=True,
                        help="Path to recipenlg_extracted_full.jsonl")
    parser.add_argument("--output", "-o", required=True,
                        help="Output path for recipenlg_subset_50k.jsonl")
    parser.add_argument("--target", "-n", type=int, default=TARGET_TOTAL,
                        help=f"Target number of recipes (default {TARGET_TOTAL})")
    return parser.parse_args()


if __name__ == "__main__":
    random.seed(42)
    args = parse_args()
    TARGET_TOTAL = args.target

    recipes = load_and_annotate(args.input)
    subset  = select_subset(recipes)
    save(subset, args.output)
