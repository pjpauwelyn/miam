"""
ingredient_parser.py — Stage 1 of the MIAM enrichment pipeline.

Parses raw ingredient strings (e.g. "2 cups all-purpose flour") into
structured (amount, unit, name, notes) tuples. Uses regex-based parsing
with heuristic fallbacks for unparseable strings.

Output: list[RecipeIngredient] objects per recipe.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.recipe import RecipeIngredient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Unit normalisation mapping → metric
# ---------------------------------------------------------------------------

UNIT_ALIASES: dict[str, str] = {
    # Volume (metric)
    "ml": "ml", "millilitre": "ml", "milliliter": "ml", "millilitres": "ml",
    "cl": "cl", "centilitre": "cl", "centiliter": "cl",
    "dl": "dl", "decilitre": "dl", "deciliter": "dl",
    "l": "ml", "litre": "ml", "liter": "ml", "litres": "ml", "liters": "ml",
    # Volume (imperial/US)
    "cup": "ml", "cups": "ml", "c": "ml",
    "tbsp": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp", "tbs": "tbsp", "tb": "tbsp",
    "tsp": "tsp", "teaspoon": "tsp", "teaspoons": "tsp", "ts": "tsp",
    "fl oz": "ml", "fluid ounce": "ml", "fluid ounces": "ml",
    "pint": "ml", "pints": "ml", "pt": "ml",
    "quart": "ml", "quarts": "ml", "qt": "ml",
    "gallon": "ml", "gallons": "ml", "gal": "ml",
    # Weight
    "g": "g", "gram": "g", "grams": "g", "gramme": "g", "grammes": "g",
    "kg": "g", "kilogram": "g", "kilograms": "g", "kilo": "g",
    "oz": "g", "ounce": "g", "ounces": "g",
    "lb": "g", "lbs": "g", "pound": "g", "pounds": "g",
    # Count/misc
    "piece": "piece", "pieces": "piece", "pc": "piece", "pcs": "piece",
    "slice": "piece", "slices": "piece",
    "clove": "piece", "cloves": "piece",
    "bunch": "bunch", "bunches": "bunch",
    "sprig": "piece", "sprigs": "piece",
    "stalk": "piece", "stalks": "piece",
    "head": "piece", "heads": "piece",
    "can": "piece", "cans": "piece", "tin": "piece", "tins": "piece",
    "jar": "piece", "jars": "piece",
    "package": "piece", "packages": "piece", "packet": "piece", "packets": "piece",
    "bag": "piece", "bags": "piece",
    "stick": "piece", "sticks": "piece",
    "leaf": "piece", "leaves": "piece",
    "pinch": "pinch", "pinches": "pinch",
    "dash": "pinch", "dashes": "pinch",
    "drop": "pinch", "drops": "pinch",
    "handful": "piece", "handfuls": "piece",
    "strip": "piece", "strips": "piece",
    "fillet": "piece", "fillets": "piece",
    "breast": "piece", "breasts": "piece",
    "thigh": "piece", "thighs": "piece",
    "leg": "piece", "legs": "piece",
    "rack": "piece", "racks": "piece",
    "ear": "piece", "ears": "piece",
}

# Conversion factors to base units (g for weight, ml for volume)
UNIT_CONVERSION: dict[str, float] = {
    # Volume → ml
    "cup": 236.588, "cups": 236.588, "c": 236.588,
    "tbsp": 14.787, "tablespoon": 14.787, "tablespoons": 14.787, "tbs": 14.787,
    "tsp": 4.929, "teaspoon": 4.929, "teaspoons": 4.929,
    "fl oz": 29.574, "fluid ounce": 29.574,
    "pint": 473.176, "pints": 473.176, "pt": 473.176,
    "quart": 946.353, "quarts": 946.353, "qt": 946.353,
    "gallon": 3785.41, "gallons": 3785.41, "gal": 3785.41,
    "l": 1000.0, "litre": 1000.0, "liter": 1000.0, "litres": 1000.0, "liters": 1000.0,
    "dl": 100.0, "decilitre": 100.0,
    "cl": 10.0, "centilitre": 10.0,
    "ml": 1.0, "millilitre": 1.0, "milliliter": 1.0,
    # Weight → g
    "kg": 1000.0, "kilogram": 1000.0, "kilograms": 1000.0, "kilo": 1000.0,
    "lb": 453.592, "lbs": 453.592, "pound": 453.592, "pounds": 453.592,
    "oz": 28.3495, "ounce": 28.3495, "ounces": 28.3495,
    "g": 1.0, "gram": 1.0, "grams": 1.0, "gramme": 1.0,
}

# Common unit strings for regex matching (ordered longest-first)
_UNIT_PATTERN_PARTS = sorted(UNIT_ALIASES.keys(), key=len, reverse=True)
_UNIT_REGEX = "|".join(re.escape(u) for u in _UNIT_PATTERN_PARTS)

# ---------------------------------------------------------------------------
# Fraction / numeric parsing
# ---------------------------------------------------------------------------

# Unicode fractions
_UNICODE_FRACTIONS: dict[str, float] = {
    "½": 0.5, "⅓": 0.333, "⅔": 0.667, "¼": 0.25, "¾": 0.75,
    "⅕": 0.2, "⅖": 0.4, "⅗": 0.6, "⅘": 0.8,
    "⅙": 0.167, "⅚": 0.833, "⅛": 0.125, "⅜": 0.375,
    "⅝": 0.625, "⅞": 0.875,
}

_FRACTION_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
_MIXED_RE = re.compile(r"(\d+)\s+(\d+)\s*/\s*(\d+)")
_RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)")


def _parse_amount(text: str) -> Optional[float]:
    """Parse a numeric amount string, handling fractions, mixed numbers, ranges."""
    text = text.strip()
    if not text:
        return None

    # Replace unicode fractions
    for uf, val in _UNICODE_FRACTIONS.items():
        if uf in text:
            # Could be "1½" (mixed) or just "½"
            text = text.replace(uf, str(val))
            # If there's a leading digit, sum them
            parts = text.strip().split()
            if len(parts) == 2:
                try:
                    return float(parts[0]) + float(parts[1])
                except ValueError:
                    pass
            try:
                return float(text)
            except ValueError:
                return None

    # Mixed number: "1 1/2"
    m = _MIXED_RE.search(text)
    if m:
        return float(m.group(1)) + float(m.group(2)) / float(m.group(3))

    # Simple fraction: "1/2"
    m = _FRACTION_RE.search(text)
    if m:
        denom = float(m.group(2))
        if denom == 0:
            return None
        return float(m.group(1)) / denom

    # Range: "2-3" → take midpoint
    m = _RANGE_RE.search(text)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2

    # Plain number
    try:
        return float(text)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Main parsing regex
# ---------------------------------------------------------------------------

# Pattern: optional amount, optional unit, then the ingredient name
# Examples:
#   "2 cups all-purpose flour"
#   "1/2 tsp salt"
#   "3 large eggs"
#   "salt and pepper to taste"
#   "1 (14 oz) can diced tomatoes"

_SIZE_ADJECTIVES = r"(?:large|medium|small|extra[- ]large|jumbo|thin|thick|big)"
_PREP_PHRASES = r"(?:,\s*(?:chopped|diced|minced|sliced|grated|crushed|peeled|seeded|" \
                r"halved|quartered|julienned|shredded|cubed|torn|trimmed|" \
                r"finely\s+(?:chopped|diced|minced|sliced|grated)|" \
                r"coarsely\s+(?:chopped|ground)|" \
                r"roughly\s+chopped|thinly\s+sliced|freshly\s+(?:ground|grated|squeezed)|" \
                r"softened|melted|room\s+temperature|at\s+room\s+temperature|" \
                r"to\s+taste|optional|divided|packed|sifted|drained|rinsed))"

_PARENTHETICAL = re.compile(r"\s*\([^)]*\)\s*")


def parse_ingredient_string(raw: str) -> RecipeIngredient:
    """
    Parse a single raw ingredient string into a RecipeIngredient.

    Strategy:
    1. Strip parenthetical notes (e.g. "(about 2 cups)")
    2. Extract leading amount
    3. Extract unit
    4. Everything else is the ingredient name + notes

    Args:
        raw: Raw ingredient string like "2 cups all-purpose flour, sifted"

    Returns:
        RecipeIngredient with parsed fields.
    """
    original = raw.strip()
    if not original:
        return RecipeIngredient(name="unknown", amount=1.0, unit="piece",
                                notes="empty input")

    # Normalise whitespace
    text = " ".join(original.split())

    # Extract parenthetical notes for later
    parens = _PARENTHETICAL.findall(text)
    paren_notes = " ".join(p.strip("() ") for p in parens) if parens else ""
    text = _PARENTHETICAL.sub(" ", text).strip()

    # Split on comma to separate prep instructions
    parts = text.split(",", 1)
    main_part = parts[0].strip()
    comma_notes = parts[1].strip() if len(parts) > 1 else ""

    # --- Extract amount ---
    amount = None
    remaining = main_part

    # Try matching a leading number (with fractions, mixed, etc.)
    amount_match = re.match(
        r"^(\d+(?:\s+\d+/\d+|\s*/\s*\d+|\.\d+)?|[½⅓⅔¼¾⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞]|\d+\s*[½⅓⅔¼¾⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞])\s*",
        remaining,
    )
    if amount_match:
        amount = _parse_amount(amount_match.group(1))
        remaining = remaining[amount_match.end():].strip()

    # --- Extract unit ---
    unit = None
    unit_match = re.match(
        r"^(" + _UNIT_REGEX + r")\b\.?\s*",
        remaining,
        re.IGNORECASE,
    )
    if unit_match:
        raw_unit = unit_match.group(1).lower().rstrip(".")
        unit = UNIT_ALIASES.get(raw_unit, raw_unit)
        remaining = remaining[unit_match.end():].strip()

    # --- Strip size adjectives from front ---
    size_match = re.match(r"^" + _SIZE_ADJECTIVES + r"\s+", remaining, re.IGNORECASE)
    if size_match:
        remaining = remaining[size_match.end():].strip()

    # --- Strip "of" connector ---
    if remaining.lower().startswith("of "):
        remaining = remaining[3:].strip()

    # --- Name is whatever remains ---
    name = remaining.strip()
    if not name:
        name = original  # fallback to full string

    # Clean up name: remove trailing periods
    name = name.rstrip(".")

    # Combine notes
    notes_parts = []
    if comma_notes:
        notes_parts.append(comma_notes)
    if paren_notes:
        notes_parts.append(paren_notes)
    notes = "; ".join(notes_parts) if notes_parts else None

    # Defaults
    if amount is None:
        amount = 1.0
    if unit is None:
        unit = "piece"

    # Detect "to taste" ingredients
    if "to taste" in original.lower():
        notes = (notes + "; to taste") if notes else "to taste"

    # Detect optional
    is_optional = "optional" in original.lower()

    return RecipeIngredient(
        name=name.lower().strip(),
        amount=round(amount, 3),
        unit=unit,
        notes=notes,
        is_optional=is_optional,
    )


def parse_recipe_ingredients(
    raw_ingredients: list[str],
    ner: list[str] | None = None,
) -> list[RecipeIngredient]:
    """
    Parse all raw ingredient strings for a recipe.

    Cross-validates parsed names against NER if available.
    Prefers the parsed name when it's more specific.

    Args:
        raw_ingredients: List of raw ingredient strings from the recipe source.
        ner: Optional NER ingredient name list for cross-validation.

    Returns:
        List of RecipeIngredient objects.
    """
    if not raw_ingredients:
        return []

    ingredients = []
    ner_lower = [n.lower().strip() for n in (ner or [])]

    for i, raw in enumerate(raw_ingredients):
        parsed = parse_ingredient_string(raw)

        # Cross-validate against NER if available
        if i < len(ner_lower) and ner_lower[i]:
            ner_name = ner_lower[i]
            parsed_name = parsed.name.lower()

            # If parsed name is more specific (longer and contains NER name), keep it
            # If NER name is more specific, use NER
            # If they're very different, prefer parsed (from structured text)
            if ner_name in parsed_name:
                pass  # parsed is more specific, keep it
            elif parsed_name in ner_name:
                parsed.name = ner_name  # NER is more specific
            # Otherwise keep parsed name (from structured ingredient string)

        ingredients.append(parsed)

    return ingredients


def estimate_grams(ingredient: RecipeIngredient) -> float:
    """
    Estimate the weight in grams for a parsed ingredient.

    Used for nutrition per-recipe calculation:
    nutrition_per_100g * (estimated_grams / 100)

    Returns estimated grams. For count-based items, uses rough approximations.
    """
    amount = ingredient.amount
    unit = ingredient.unit.lower()

    # Direct weight units
    if unit == "g":
        return amount
    if unit in ("kg",):
        return amount * 1000

    # Check conversion factor for volume units
    raw_unit = None
    for alias, norm in UNIT_ALIASES.items():
        if norm == unit or alias == unit:
            if alias in UNIT_CONVERSION:
                raw_unit = alias
                break

    if raw_unit and raw_unit in UNIT_CONVERSION:
        # Volume to ml, then approximate ml ≈ grams for most food
        ml = amount * UNIT_CONVERSION[raw_unit]
        return ml  # Rough approximation: 1 ml ≈ 1 g for most ingredients

    # Count-based items: rough weight estimates
    _PIECE_WEIGHTS: dict[str, float] = {
        "egg": 60, "eggs": 60,
        "onion": 150, "garlic": 5, "shallot": 30,
        "potato": 170, "sweet potato": 200, "carrot": 80,
        "tomato": 125, "pepper": 150, "capsicum": 150,
        "apple": 180, "banana": 120, "lemon": 85, "lime": 65,
        "orange": 150, "avocado": 170,
        "chicken breast": 200, "chicken thigh": 150,
        "salmon fillet": 150, "fish fillet": 150,
    }

    if unit == "piece":
        name_lower = ingredient.name.lower()
        for key, weight in _PIECE_WEIGHTS.items():
            if key in name_lower:
                return amount * weight
        return amount * 100  # default: 100g per piece

    if unit == "bunch":
        return amount * 50  # rough estimate

    if unit == "pinch":
        return amount * 0.5  # ~0.5g per pinch

    if unit == "tbsp":
        return amount * 15  # ~15g per tablespoon

    if unit == "tsp":
        return amount * 5  # ~5g per teaspoon

    if unit == "ml":
        return amount  # 1 ml ≈ 1 g

    # Fallback
    return amount * 100
