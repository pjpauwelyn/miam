"""
DietaryInferenceEngine — rule-based dietary flag inference from ingredient lists.

Maps ingredient NER names to the 12 DietaryFlags booleans.
Uses curated term lists covering EU/British English and US English variants
for maximum recall (e.g. both "prawn" and "shrimp", "aubergine" and "eggplant").

All term lists are lowercase. Matching is substring-based on normalised names.
"""
from __future__ import annotations

import logging
import re
from typing import Sequence

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.recipe import DietaryFlags

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ingredient term lists — lowercase, used for substring matching
# ---------------------------------------------------------------------------

MEAT_TERMS: set[str] = {
    "beef", "steak", "veal", "lamb", "mutton", "pork", "bacon", "ham",
    "prosciutto", "pancetta", "salami", "chorizo", "sausage", "pepperoni",
    "mince", "minced", "ground beef", "ground pork", "ground lamb",
    "venison", "rabbit", "duck", "goose", "turkey", "chicken", "poultry",
    "quail", "pheasant", "partridge", "pigeon", "liver", "kidney",
    "offal", "tripe", "tongue", "oxtail", "brisket", "rib", "loin",
    "gammon", "bratwurst", "frankfurter", "hot dog", "mortadella",
    "bresaola", "coppa", "nduja", "sobrassada", "boudin", "rillettes",
    "paté", "pate", "terrine", "suet", "dripping", "lard",
    "bone marrow", "stock bone", "gelatin", "gelatine",
}

POULTRY_TERMS: set[str] = {
    "chicken", "turkey", "duck", "goose", "quail", "pheasant",
    "partridge", "pigeon", "guinea fowl", "cornish hen", "capon",
}

FISH_TERMS: set[str] = {
    "fish", "salmon", "tuna", "cod", "haddock", "mackerel", "sardine",
    "anchovy", "anchovies", "herring", "trout", "sea bass", "sole",
    "plaice", "halibut", "swordfish", "monkfish", "snapper", "pike",
    "perch", "catfish", "tilapia", "pollock", "whitebait", "sprat",
    "eel", "bream", "dory", "grouper", "mahi", "wahoo", "barramundi",
    "fish sauce", "fish stock", "bonito", "dashi",
    "worcestershire",  # contains anchovies
}

SHELLFISH_TERMS: set[str] = {
    "shrimp", "prawn", "king prawn", "crab", "lobster", "crayfish",
    "mussel", "clam", "oyster", "scallop", "squid", "calamari",
    "octopus", "cockle", "whelk", "langoustine", "crawfish",
    "abalone", "sea urchin", "cuttlefish",
}

PORK_TERMS: set[str] = {
    "pork", "bacon", "ham", "prosciutto", "pancetta", "salami",
    "chorizo", "pepperoni", "sausage", "lard", "gammon",
    "bratwurst", "frankfurter", "hot dog", "mortadella",
    "coppa", "nduja", "sobrassada", "boudin", "rillettes",
    "crackling", "chicharron",
}

ALCOHOL_TERMS: set[str] = {
    "wine", "red wine", "white wine", "beer", "ale", "lager", "stout",
    "brandy", "cognac", "rum", "vodka", "whisky", "whiskey", "gin",
    "tequila", "mezcal", "liqueur", "amaretto", "kahlua", "baileys",
    "champagne", "prosecco", "cava", "sherry", "port", "marsala",
    "madeira", "vermouth", "sake", "mirin", "kirsch", "grappa",
    "calvados", "armagnac", "absinthe", "ouzo", "raki", "sambuca",
    "limoncello", "grand marnier", "cointreau", "curaçao", "curacao",
}

DAIRY_TERMS: set[str] = {
    "milk", "cream", "butter", "cheese", "yoghurt", "yogurt",
    "curd", "whey", "casein", "ghee", "mascarpone", "ricotta",
    "mozzarella", "parmesan", "parmigiano", "cheddar", "gruyère",
    "gruyere", "brie", "camembert", "gouda", "emmental", "feta",
    "halloumi", "paneer", "cottage cheese", "cream cheese",
    "sour cream", "crème fraîche", "creme fraiche",
    "double cream", "single cream", "heavy cream", "light cream",
    "clotted cream", "buttermilk", "condensed milk", "evaporated milk",
    "full-fat milk", "semi-skimmed milk", "skimmed milk", "whole milk",
    "2% milk", "skim milk",
    "ice cream", "custard", "bechamel", "béchamel",
    "quark", "labneh", "kefir", "fromage",
}

EGG_TERMS: set[str] = {
    "egg", "eggs", "egg yolk", "egg white", "meringue", "mayonnaise",
    "aioli", "hollandaise", "quiche", "frittata", "omelette", "omelet",
}

HONEY_TERMS: set[str] = {
    "honey",
}

GLUTEN_TERMS: set[str] = {
    "wheat", "flour", "bread", "pasta", "noodle", "spaghetti",
    "penne", "fusilli", "lasagne", "lasagna", "macaroni", "fettuccine",
    "linguine", "tagliatelle", "ravioli", "tortellini", "gnocchi",
    "couscous", "bulgur", "semolina", "seitan",
    "barley", "rye", "spelt", "kamut", "triticale",
    "breadcrumb", "crouton", "panko", "pita", "pitta", "naan",
    "tortilla", "wrap", "baguette", "ciabatta", "focaccia",
    "croissant", "pastry", "puff pastry", "filo", "phyllo",
    "plain flour", "self-raising flour", "strong flour",
    "all-purpose flour", "bread flour", "cake flour",
    "wholemeal flour", "whole wheat flour",
    "soy sauce",  # typically contains wheat
    "malt", "malt vinegar",
    "beer", "ale", "lager", "stout",  # barley-based
}

NUT_TERMS: set[str] = {
    "almond", "walnut", "cashew", "pistachio", "hazelnut", "pecan",
    "macadamia", "brazil nut", "pine nut", "chestnut",
    "peanut",  # technically a legume but commonly grouped with nut allergies
    "nut butter", "almond butter", "peanut butter", "cashew butter",
    "almond milk", "almond flour", "ground almond",
    "marzipan", "frangipane", "praline", "nougat", "gianduja",
    "nutella", "tahini",  # sesame, often grouped with nut warnings
}


# ---------------------------------------------------------------------------
# Helper: check if any term from a set appears in an ingredient name
# ---------------------------------------------------------------------------

def _contains_any(ingredient: str, terms: set[str]) -> bool:
    """Check if the ingredient name contains any of the given terms (substring match)."""
    ing_lower = ingredient.lower().strip()
    for term in terms:
        # Use word boundary matching to reduce false positives
        # e.g. "wine" should not match "wintergreen"
        if re.search(r'\b' + re.escape(term) + r'\b', ing_lower):
            return True
    return False


def _any_ingredient_contains(ingredients: list[str], terms: set[str]) -> bool:
    """Check if any ingredient in the list matches any term."""
    return any(_contains_any(ing, terms) for ing in ingredients)


# ---------------------------------------------------------------------------
# Main inference function
# ---------------------------------------------------------------------------

class DietaryInferenceEngine:
    """
    Rule-based engine for inferring DietaryFlags from ingredient NER lists.

    Usage:
        engine = DietaryInferenceEngine()
        flags = engine.infer_flags(["chicken", "rice", "soy sauce", "ginger"])
        # flags.is_vegan == False, flags.is_gluten_free == False (soy sauce), etc.
    """

    def infer_flags(self, ner_ingredients: Sequence[str]) -> DietaryFlags:
        """
        Infer all 12 dietary boolean flags from a list of NER ingredient names.

        Args:
            ner_ingredients: List of clean ingredient names from RecipeNLG NER column.

        Returns:
            Populated DietaryFlags instance.
        """
        ingredients = [ing.lower().strip() for ing in ner_ingredients if ing.strip()]

        has_meat = _any_ingredient_contains(ingredients, MEAT_TERMS)
        has_poultry = _any_ingredient_contains(ingredients, POULTRY_TERMS)
        has_fish = _any_ingredient_contains(ingredients, FISH_TERMS)
        has_shellfish = _any_ingredient_contains(ingredients, SHELLFISH_TERMS)
        has_pork = _any_ingredient_contains(ingredients, PORK_TERMS)
        has_alcohol = _any_ingredient_contains(ingredients, ALCOHOL_TERMS)
        has_dairy = _any_ingredient_contains(ingredients, DAIRY_TERMS)
        has_eggs = _any_ingredient_contains(ingredients, EGG_TERMS)
        has_honey = _any_ingredient_contains(ingredients, HONEY_TERMS)
        has_gluten = _any_ingredient_contains(ingredients, GLUTEN_TERMS)
        has_nuts = _any_ingredient_contains(ingredients, NUT_TERMS)

        # Derived flags
        has_any_animal_flesh = has_meat or has_poultry or has_fish or has_shellfish
        has_any_animal_product = has_any_animal_flesh or has_dairy or has_eggs or has_honey

        is_vegetarian = not has_any_animal_flesh
        is_vegan = not has_any_animal_product
        is_pescatarian_ok = is_vegetarian or (
            not has_meat and not has_poultry and (has_fish or has_shellfish)
        )

        # "vegan if substituted" — vegetarian recipes that only need dairy/egg swaps
        vegan_if_substituted = (
            is_vegetarian
            and not is_vegan
            and (has_dairy or has_eggs or has_honey)
            and not has_any_animal_flesh
        )

        # "gluten-free if substituted" — recipes where gluten comes only from
        # easily swappable items (flour, pasta, bread, soy sauce)
        gluten_free_if_substituted = has_gluten and not is_vegan  # rough heuristic

        is_halal_ok = not has_pork and not has_alcohol

        return DietaryFlags(
            is_vegan=is_vegan,
            is_vegetarian=is_vegetarian,
            is_pescatarian_ok=is_pescatarian_ok,
            is_dairy_free=not has_dairy,
            is_gluten_free=not has_gluten,
            is_nut_free=not has_nuts,
            is_halal_ok=is_halal_ok,
            contains_pork=has_pork,
            contains_shellfish=has_shellfish,
            contains_alcohol=has_alcohol,
            vegan_if_substituted=vegan_if_substituted,
            gluten_free_if_substituted=gluten_free_if_substituted,
        )

    def dietary_tags_from_flags(self, flags: DietaryFlags) -> list[str]:
        """
        Generate human-readable dietary_tags list from DietaryFlags.
        Used for the dietary_tags field on RecipeDocument.
        """
        tags: list[str] = []
        if flags.is_vegan:
            tags.append("vegan")
        elif flags.is_vegetarian:
            tags.append("vegetarian")
        if flags.is_pescatarian_ok and not flags.is_vegetarian:
            tags.append("pescatarian")
        if flags.is_dairy_free:
            tags.append("dairy-free")
        if flags.is_gluten_free:
            tags.append("gluten-free")
        if flags.is_nut_free:
            tags.append("nut-free")
        if flags.is_halal_ok:
            tags.append("halal-friendly")
        if flags.contains_pork:
            tags.append("contains-pork")
        if flags.contains_shellfish:
            tags.append("contains-shellfish")
        if flags.contains_alcohol:
            tags.append("contains-alcohol")
        if flags.vegan_if_substituted:
            tags.append("vegan-if-substituted")
        if flags.gluten_free_if_substituted:
            tags.append("gluten-free-if-substituted")
        return tags


# Module-level singleton
_instance: DietaryInferenceEngine | None = None


def get_dietary_engine() -> DietaryInferenceEngine:
    """Get or create the singleton DietaryInferenceEngine instance."""
    global _instance
    if _instance is None:
        _instance = DietaryInferenceEngine()
    return _instance
