"""
allergen_detector.py — EU-14 major allergen detection from ingredient lists.

Implements allergen warnings per EU Regulation EC No 1169/2011.
Fully deterministic: maps ingredient NER names against curated term lists
for the 14 declarable allergens.

Output: list[str] of allergen categories present in the recipe.
"""
from __future__ import annotations

import logging
import re
from typing import Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# EU 14 Major Allergens — term lists for ingredient matching
# Each set contains lowercase terms that trigger the allergen declaration.
# Uses word-boundary matching to reduce false positives.
# ---------------------------------------------------------------------------

ALLERGEN_TERMS: dict[str, set[str]] = {
    "celery": {
        "celery", "celeriac", "celery salt", "celery seed",
    },
    "cereals": {
        "wheat", "flour", "bread", "pasta", "noodle", "couscous", "bulgur",
        "semolina", "spelt", "kamut", "triticale", "barley", "rye",
        "oat", "oats", "oatmeal", "seitan",
        "spaghetti", "penne", "fusilli", "lasagne", "lasagna", "macaroni",
        "fettuccine", "linguine", "tagliatelle", "ravioli", "tortellini",
        "gnocchi", "breadcrumb", "crouton", "panko",
        "pita", "pitta", "naan", "tortilla", "wrap",
        "baguette", "ciabatta", "focaccia", "croissant", "pastry",
        "puff pastry", "filo", "phyllo",
        "plain flour", "self-raising flour", "strong flour",
        "all-purpose flour", "bread flour", "cake flour",
        "wholemeal flour", "whole wheat flour",
        "malt", "malt vinegar",
    },
    "crustaceans": {
        "shrimp", "prawn", "king prawn", "crab", "lobster", "crayfish",
        "crawfish", "langoustine", "scampi",
    },
    "eggs": {
        "egg", "eggs", "egg yolk", "egg white", "meringue",
        "mayonnaise", "aioli", "hollandaise",
    },
    "fish": {
        "fish", "salmon", "tuna", "cod", "haddock", "mackerel", "sardine",
        "anchovy", "anchovies", "herring", "trout", "sea bass", "sole",
        "plaice", "halibut", "swordfish", "monkfish", "snapper", "pike",
        "perch", "catfish", "tilapia", "pollock", "whitebait", "sprat",
        "eel", "bream", "dory", "grouper", "mahi", "wahoo", "barramundi",
        "fish sauce", "fish stock", "bonito", "dashi",
        "worcestershire",
    },
    "lupin": {
        "lupin", "lupine", "lupin flour", "lupin seed",
    },
    "milk": {
        "milk", "cream", "butter", "cheese", "yoghurt", "yogurt",
        "curd", "whey", "casein", "ghee", "mascarpone", "ricotta",
        "mozzarella", "parmesan", "parmigiano", "cheddar", "gruyère",
        "gruyere", "brie", "camembert", "gouda", "emmental", "feta",
        "halloumi", "paneer", "cottage cheese", "cream cheese",
        "sour cream", "crème fraîche", "creme fraiche",
        "double cream", "single cream", "heavy cream", "light cream",
        "clotted cream", "buttermilk", "condensed milk", "evaporated milk",
        "ice cream", "custard", "bechamel", "béchamel",
        "quark", "labneh", "kefir", "fromage",
    },
    "molluscs": {
        "mussel", "clam", "oyster", "scallop", "squid", "calamari",
        "octopus", "cockle", "whelk", "abalone", "cuttlefish",
        "sea urchin", "snail", "escargot",
    },
    "mustard": {
        "mustard", "dijon", "mustard seed", "mustard powder",
        "english mustard", "wholegrain mustard",
    },
    "nuts": {
        "almond", "walnut", "cashew", "pistachio", "hazelnut", "pecan",
        "macadamia", "brazil nut", "pine nut", "chestnut",
        "nut butter", "almond butter", "cashew butter",
        "almond milk", "almond flour", "ground almond",
        "marzipan", "frangipane", "praline", "nougat", "gianduja",
    },
    "peanuts": {
        "peanut", "peanuts", "peanut butter", "groundnut",
        "monkey nut", "arachis",
    },
    "sesame": {
        "sesame", "sesame seed", "sesame oil", "tahini",
        "sesame paste", "halvah", "halva",
    },
    "soybeans": {
        "soy", "soya", "soy sauce", "soybean", "soybeans",
        "tofu", "tempeh", "edamame", "miso", "natto",
        "soy milk", "soy cream", "soy yoghurt",
        "tamari", "teriyaki",
    },
    "sulphites": {
        "sulphite", "sulfite", "sulphur dioxide",
        "dried fruit", "dried apricot", "dried cranberry",
        "wine", "red wine", "white wine",
        "vinegar", "wine vinegar",
        "molasses", "treacle",
    },
}


def _contains_any(ingredient: str, terms: set[str]) -> bool:
    """Check if the ingredient name contains any term (word-boundary match)."""
    ing_lower = ingredient.lower().strip()
    for term in terms:
        if re.search(r"\b" + re.escape(term) + r"\b", ing_lower):
            return True
    return False


def detect_allergens(ingredients: Sequence[str]) -> list[str]:
    """
    Detect EU-14 major allergens from a list of ingredient names.

    Args:
        ingredients: List of ingredient names (NER or parsed names).

    Returns:
        Sorted list of allergen category strings present in the recipe.
        Values from: celery, cereals, crustaceans, eggs, fish, lupin,
        milk, molluscs, mustard, nuts, peanuts, sesame, soybeans, sulphites.
    """
    found_allergens: set[str] = set()

    for ingredient in ingredients:
        if not ingredient or not ingredient.strip():
            continue
        for allergen_name, terms in ALLERGEN_TERMS.items():
            if allergen_name not in found_allergens:
                if _contains_any(ingredient, terms):
                    found_allergens.add(allergen_name)

    return sorted(found_allergens)


def allergen_display_string(allergens: list[str]) -> str:
    """
    Format allergens for display: "Contains: eggs, milk, nuts"
    Returns empty string if no allergens.
    """
    if not allergens:
        return ""
    return "Contains: " + ", ".join(allergens)
