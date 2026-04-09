"""
EU <-> US ingredient name mapping.

miam uses EU/British English ingredient names throughout.
This resolver maps US names to their EU equivalents and vice versa,
used during query ontology extraction and recipe search.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Canonical: EU/British English -> US English
# All ingredient names in the miam corpus use EU/British English.
EU_TO_US: dict[str, str] = {
    "aubergine": "eggplant",
    "courgette": "zucchini",
    "coriander": "cilantro",
    "spring onion": "scallion",
    "rocket": "arugula",
    "chips": "fries",
    "crisps": "chips",
    "mince": "ground meat",
    "minced beef": "ground beef",
    "minced pork": "ground pork",
    "minced lamb": "ground lamb",
    "double cream": "heavy cream",
    "single cream": "light cream",
    "caster sugar": "superfine sugar",
    "icing sugar": "powdered sugar",
    "plain flour": "all-purpose flour",
    "strong flour": "bread flour",
    "wholemeal flour": "whole wheat flour",
    "bicarbonate of soda": "baking soda",
    "biscuit": "cookie",
    "broad beans": "fava beans",
    "swede": "rutabaga",
    "mange tout": "snow peas",
    "king prawn": "jumbo shrimp",
    "prawn": "shrimp",
    "streaky bacon": "bacon",
    "back bacon": "canadian bacon",
    "gammon": "ham steak",
    "rapeseed oil": "canola oil",
    "natural yoghurt": "plain yogurt",
    "full-fat milk": "whole milk",
    "semi-skimmed milk": "2% milk",
    "skimmed milk": "skim milk",
    "pepper (capsicum)": "bell pepper",
    "capsicum": "bell pepper",
    "chilli": "chili",
    "beetroot": "beet",
    "sweetcorn": "corn",
    "tin": "can",
    "tinned tomatoes": "canned tomatoes",
    "stock cube": "bouillon cube",
    "cling film": "plastic wrap",
    "greaseproof paper": "parchment paper",
    "grill": "broil",
    "liquidiser": "blender",
    "measure": "measuring cup",
}

# Reverse mapping: US -> EU
US_TO_EU: dict[str, str] = {v: k for k, v in EU_TO_US.items()}


def to_eu(ingredient: str) -> str:
    """
    Convert a US ingredient name to EU/British English.
    Case-insensitive lookup; returns original if no mapping exists.
    """
    normalized = ingredient.strip().lower()
    eu_name = US_TO_EU.get(normalized)
    if eu_name:
        logger.debug("Resolved US '%s' -> EU '%s'", ingredient, eu_name)
        return eu_name
    return ingredient


def to_us(ingredient: str) -> str:
    """
    Convert an EU/British English ingredient name to US English.
    Case-insensitive lookup; returns original if no mapping exists.
    """
    normalized = ingredient.strip().lower()
    us_name = EU_TO_US.get(normalized)
    if us_name:
        logger.debug("Resolved EU '%s' -> US '%s'", ingredient, us_name)
        return us_name
    return ingredient


def normalize_ingredient(ingredient: str) -> str:
    """
    Normalize an ingredient name to EU/British English (canonical form).
    First checks if it's a US name that needs converting.
    """
    return to_eu(ingredient)


def get_all_variants(ingredient: str) -> list[str]:
    """
    Get all known variants of an ingredient name (EU + US).
    Useful for search expansion.
    """
    normalized = ingredient.strip().lower()
    variants = {normalized}

    # Check EU -> US
    if normalized in EU_TO_US:
        variants.add(EU_TO_US[normalized])
    # Check US -> EU
    if normalized in US_TO_EU:
        variants.add(US_TO_EU[normalized])

    return list(variants)
