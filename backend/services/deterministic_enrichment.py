"""
deterministic_enrichment.py — Stage 5 of the MIAM enrichment pipeline.

Computes fields that the plan designates as deterministically derivable
rather than LLM-generated:

- difficulty (1–5): from ingredient count + technique complexity + time
- season_tags: from ingredient seasonality lookup
- flavor_tags: from FlavorDB entity lookup
- texture_tags: from technique → texture mapping
- ingredient_category: from curated category lookup

All lookups use JSON reference files in backend/data/.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional, Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data directory
# ---------------------------------------------------------------------------

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

# ---------------------------------------------------------------------------
# Lazy-loaded reference data
# ---------------------------------------------------------------------------

_seasonality: dict[str, list[int]] | None = None
_flavordb: dict[str, list[str]] | None = None
_categories: dict[str, str] | None = None

# Pantry staples excluded from seasonality calculations
PANTRY_STAPLES: frozenset[str] = frozenset({
    "salt", "pepper", "black pepper", "white pepper",
    "sugar", "brown sugar", "icing sugar", "caster sugar",
    "flour", "plain flour", "self-raising flour", "all-purpose flour",
    "bread flour", "cake flour", "cornflour", "cornstarch",
    "olive oil", "vegetable oil", "sunflower oil", "canola oil",
    "coconut oil", "sesame oil", "rapeseed oil",
    "butter", "ghee", "lard",
    "vinegar", "wine vinegar", "balsamic vinegar", "rice vinegar",
    "soy sauce", "fish sauce", "worcestershire", "worcestershire sauce",
    "tomato paste", "tomato puree", "passata",
    "stock", "chicken stock", "beef stock", "vegetable stock",
    "broth", "chicken broth", "beef broth",
    "water", "ice",
    "baking powder", "baking soda", "bicarbonate of soda",
    "yeast", "dried yeast", "active dry yeast",
    "vanilla", "vanilla extract", "vanilla essence",
    "cocoa", "cocoa powder", "chocolate",
    "honey", "maple syrup", "golden syrup", "treacle", "molasses",
    "mustard", "dijon mustard", "english mustard",
    "ketchup", "mayonnaise",
    "garlic", "onion", "shallot",
    "dried herbs", "mixed herbs", "italian seasoning",
    "cumin", "paprika", "turmeric", "cinnamon", "nutmeg",
    "cayenne", "chili powder", "chilli powder", "chili flakes",
    "oregano", "thyme", "rosemary", "bay leaf", "bay leaves",
    "coriander", "cumin seeds", "mustard seeds",
    "ginger", "ground ginger",
    "cream of tartar", "gelatin", "gelatine",
    "rice", "pasta", "noodles", "egg noodles",
    "lemon juice", "lime juice",
})

# Season month ranges
SEASONS: dict[str, list[int]] = {
    "spring": [3, 4, 5],
    "summer": [6, 7, 8],
    "autumn": [9, 10, 11],
    "winter": [12, 1, 2],
}

# FlavorDB descriptors → MIAM FLAVOR_VOCAB mapping
FLAVOR_TAG_MAP: dict[str, str] = {
    # umami
    "savory": "umami", "meaty": "umami", "brothy": "umami",
    "fermented": "umami", "umami": "umami",
    # acidic
    "tart": "acidic", "sour": "acidic", "citrus": "acidic",
    "vinegary": "acidic", "acidic": "acidic",
    # sweet
    "sweet": "sweet", "caramel": "sweet", "honey": "sweet",
    "fruity": "sweet", "sugary": "sweet",
    # bitter
    "bitter": "bitter", "astringent": "bitter", "coffee": "bitter",
    # spicy
    "hot": "spicy", "peppery": "spicy", "pungent": "spicy",
    "sharp": "spicy", "spicy": "spicy",
    # herbaceous
    "herbal": "herbaceous", "grassy": "herbaceous", "minty": "herbaceous",
    "fresh": "herbaceous", "aromatic": "herbaceous", "herbaceous": "herbaceous",
    # smoky
    "smoky": "smoky", "charred": "smoky", "toasted": "smoky",
    "roasted": "smoky",
    # rich
    "buttery": "rich", "fatty": "rich", "creamy": "rich",
    "nutty": "rich", "rich": "rich",
    # light
    "delicate": "light", "mild": "light", "clean": "light",
    "subtle": "light", "light": "light",
    # tangy
    "tangy": "tangy", "zesty": "tangy", "bright": "tangy",
    # earthy
    "earthy": "earthy", "mushroomy": "earthy", "woody": "earthy",
    "mossy": "earthy", "truffle": "earthy",
    # floral
    "floral": "floral", "rose": "floral", "lavender": "floral",
    "violet": "floral",
    # savoury (alias)
    "savoury": "umami",
    # sulfurous → spicy/pungent
    "sulfurous": "spicy",
    # briny → umami
    "briny": "umami",
}


def _load_seasonality() -> dict[str, list[int]]:
    global _seasonality
    if _seasonality is None:
        path = os.path.join(_DATA_DIR, "ingredient_seasonality.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                _seasonality = json.load(f)
            logger.info("Loaded seasonality data: %d ingredients", len(_seasonality))
        else:
            logger.warning("Seasonality data not found at %s", path)
            _seasonality = {}
    return _seasonality


def _load_flavordb() -> dict[str, list[str]]:
    global _flavordb
    if _flavordb is None:
        path = os.path.join(_DATA_DIR, "flavordb_entities.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                _flavordb = json.load(f)
            logger.info("Loaded FlavorDB data: %d entities", len(_flavordb))
        else:
            logger.warning("FlavorDB data not found at %s", path)
            _flavordb = {}
    return _flavordb


def _load_categories() -> dict[str, str]:
    global _categories
    if _categories is None:
        path = os.path.join(_DATA_DIR, "ingredient_categories.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                _categories = json.load(f)
            logger.info("Loaded ingredient categories: %d entries", len(_categories))
        else:
            logger.warning("Ingredient categories not found at %s", path)
            _categories = {}
    return _categories


# ---------------------------------------------------------------------------
# Difficulty computation
# ---------------------------------------------------------------------------

def compute_difficulty(
    ingredient_count: int,
    technique_set: set[str],
    total_time_min: Optional[int],
    hard_techniques: frozenset[str] | None = None,
) -> int:
    """
    Compute recipe difficulty on a 1–5 scale.

    Factors:
    - Ingredient count: 5–15 is moderate, >15 is complex
    - Technique complexity: hard techniques add difficulty
    - Total time: longer recipes tend to be harder

    Args:
        ingredient_count: Number of parsed ingredients.
        technique_set: Set of technique tag strings detected.
        total_time_min: Total cooking time in minutes (or None).
        hard_techniques: Override for hard technique set.

    Returns:
        Integer difficulty 1–5.
    """
    from services.technique_extractor import HARD_TECHNIQUES as DEFAULT_HARD

    if hard_techniques is None:
        hard_techniques = DEFAULT_HARD

    time_min = total_time_min or 30
    hard_count = len(technique_set & hard_techniques)

    # Normalised scores (0–1)
    ing_score = min(ingredient_count / 15, 1.0)
    tech_score = min(hard_count / 3, 1.0)
    time_score = min(time_min / 120, 1.0)

    # Weighted composite (0–100)
    complexity = (
        ing_score * 30        # ingredient complexity
        + tech_score * 40     # technique complexity
        + time_score * 30     # time complexity
    )

    return max(1, min(5, round(complexity / 20)))


# ---------------------------------------------------------------------------
# Season tags
# ---------------------------------------------------------------------------

def compute_season_tags(
    ingredient_names: Sequence[str],
    threshold: float = 0.6,
) -> list[str]:
    """
    Determine season tags based on ingredient seasonality.

    A recipe is tagged for a season if ≥threshold of its non-pantry
    ingredients are in season during those months.

    Args:
        ingredient_names: List of ingredient names.
        threshold: Fraction of seasonal ingredients required.

    Returns:
        List of season tag strings (e.g. ["spring", "summer"]).
    """
    seasonality = _load_seasonality()

    # Filter out pantry staples
    seasonal_ingredients = [
        name.lower().strip() for name in ingredient_names
        if name.lower().strip() not in PANTRY_STAPLES
    ]

    if not seasonal_ingredients:
        return ["year-round"]

    # For each season, check how many ingredients are in season
    season_scores: dict[str, float] = {}

    for season_name, months in SEASONS.items():
        in_season_count = 0
        known_count = 0

        for ing in seasonal_ingredients:
            # Try exact match first, then substring match
            ing_months = seasonality.get(ing)
            if ing_months is None:
                # Try partial matching
                for key, months_list in seasonality.items():
                    if key in ing or ing in key:
                        ing_months = months_list
                        break

            if ing_months is not None:
                known_count += 1
                # Check if any of the season months overlap
                if any(m in ing_months for m in months):
                    in_season_count += 1

        if known_count > 0:
            season_scores[season_name] = in_season_count / known_count
        else:
            season_scores[season_name] = 1.0  # unknown = assume year-round

    # Select seasons above threshold
    tags = [s for s, score in season_scores.items() if score >= threshold]

    if not tags or len(tags) == 4:
        return ["year-round"]

    return sorted(tags, key=lambda s: list(SEASONS.keys()).index(s))


# ---------------------------------------------------------------------------
# Flavor tags
# ---------------------------------------------------------------------------

def compute_flavor_tags(
    ingredient_names: Sequence[str],
    max_tags: int = 3,
) -> list[str]:
    """
    Derive flavor tags from ingredient names using FlavorDB data.

    Aggregates flavor descriptors across all ingredients and returns
    the top N most frequent, mapped to the MIAM FLAVOR_VOCAB.

    Args:
        ingredient_names: List of ingredient names.
        max_tags: Maximum number of flavor tags to return.

    Returns:
        List of flavor tag strings from FLAVOR_VOCAB.
    """
    flavordb = _load_flavordb()

    # Count mapped flavor tags across all ingredients
    tag_counts: dict[str, int] = {}

    for name in ingredient_names:
        name_lower = name.lower().strip()

        # Try exact match first, then substring
        descriptors = flavordb.get(name_lower)
        if descriptors is None:
            for key, descs in flavordb.items():
                if key in name_lower or name_lower in key:
                    descriptors = descs
                    break

        if descriptors:
            for desc in descriptors:
                mapped = FLAVOR_TAG_MAP.get(desc.lower())
                if mapped:
                    tag_counts[mapped] = tag_counts.get(mapped, 0) + 1

    if not tag_counts:
        return []

    # Sort by frequency, take top N
    sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
    return [tag for tag, _ in sorted_tags[:max_tags]]


# ---------------------------------------------------------------------------
# Ingredient categories
# ---------------------------------------------------------------------------

def categorise_ingredient(name: str) -> Optional[str]:
    """
    Look up the category for a single ingredient.

    Returns one of: protein, vegetable, starch, fat, spice, herb,
    liquid, condiment, dairy, fruit, sweetener. Or None if not found.
    """
    categories = _load_categories()
    name_lower = name.lower().strip()

    # Exact match
    cat = categories.get(name_lower)
    if cat:
        return cat

    # Substring match (ingredient name might be more specific)
    for key, cat in categories.items():
        if key in name_lower or name_lower in key:
            return cat

    return None


def categorise_ingredients(names: Sequence[str]) -> dict[str, Optional[str]]:
    """
    Categorise a list of ingredient names.

    Returns:
        Dict mapping ingredient name → category string or None.
    """
    return {name: categorise_ingredient(name) for name in names}
