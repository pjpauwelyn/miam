"""
technique_extractor.py — Stage 2 of the MIAM enrichment pipeline.

Extracts cooking technique tags from recipe step text using regex patterns.
Vocabulary derived from RecipeDB's 268 cooking processes and FoodOn's
food transformation ontology, collapsed to ~20 practical tags.

Each step gets its own technique_tags list. The recipe-level technique set
is the union of all step-level tags.
"""
from __future__ import annotations

import logging
import re
from typing import Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Technique patterns — regex for each cooking technique
# ---------------------------------------------------------------------------

TECHNIQUE_PATTERNS: dict[str, re.Pattern] = {
    "roast": re.compile(
        r"\b(roast|roasting|roasted|oven[- ]roast)\b", re.IGNORECASE
    ),
    "bake": re.compile(
        r"\b(bak[ei]|baking|baked|oven[- ]bak)\b", re.IGNORECASE
    ),
    "fry": re.compile(
        r"\b(fr[yi]|frying|fried|pan[- ]fr[yi]|deep[- ]fr[yi]|"
        r"stir[- ]fr[yi]|shallow[- ]fr[yi]|flash[- ]fr[yi])\b",
        re.IGNORECASE,
    ),
    "sauté": re.compile(
        r"\b(saut[eé]|saut[eé]ing|saut[eé]ed|sautée?)\b", re.IGNORECASE
    ),
    "grill": re.compile(
        r"\b(grill|grilling|grilled|char[- ]?grill|broil|broiling|broiled)\b",
        re.IGNORECASE,
    ),
    "steam": re.compile(
        r"\b(steam|steaming|steamed)\b", re.IGNORECASE
    ),
    "boil": re.compile(
        r"\b(boil|boiling|boiled|blanch|blanching|blanched|parboil)\b",
        re.IGNORECASE,
    ),
    "simmer": re.compile(
        r"\b(simmer|simmering|simmered)\b", re.IGNORECASE
    ),
    "braise": re.compile(
        r"\b(brais[ei]|braising|braised|slow[- ]cook|slow[- ]cooking|slow[- ]cooked)\b",
        re.IGNORECASE,
    ),
    "poach": re.compile(
        r"\b(poach|poaching|poached)\b", re.IGNORECASE
    ),
    "smoke": re.compile(
        r"\b(smok[ei]|smoking|smoked|cold[- ]smok|hot[- ]smok)\b",
        re.IGNORECASE,
    ),
    "ferment": re.compile(
        r"\b(ferment|fermenting|fermented|pickl[ei]|pickling|pickled|"
        r"cur[ei]|curing|cured|brin[ei]|brining|brined)\b",
        re.IGNORECASE,
    ),
    "marinate": re.compile(
        r"\b(marinat[ei]|marinating|marinated|marinade)\b", re.IGNORECASE
    ),
    "reduce": re.compile(
        r"\b(reduc[ei]|reducing|reduced|reduction|deglaz[ei]|deglazing|deglazed)\b",
        re.IGNORECASE,
    ),
    "caramelise": re.compile(
        r"\b(carameli[sz]e|carameli[sz]ing|carameli[sz]ed|caramelisation|caramelization)\b",
        re.IGNORECASE,
    ),
    "whisk": re.compile(
        r"\b(whisk|whisking|whisked|whip|whipping|whipped|beat|beating|beaten)\b",
        re.IGNORECASE,
    ),
    "knead": re.compile(
        r"\b(knead|kneading|kneaded|prov[ei]|proving|proved|proof|proofing)\b",
        re.IGNORECASE,
    ),
    "fold": re.compile(
        r"\b(fold|folding|folded)\b", re.IGNORECASE
    ),
    "blend": re.compile(
        r"\b(blend|blending|blended|pur[eé]e|pureeing|pureed|"
        r"process|processing|processed|liquidis|liquidiz)\b",
        re.IGNORECASE,
    ),
    "toast": re.compile(
        r"\b(toast|toasting|toasted|dry[- ]roast)\b", re.IGNORECASE
    ),
}

# ---------------------------------------------------------------------------
# Technique → difficulty mapping (1–5 scale)
# ---------------------------------------------------------------------------

TECHNIQUE_DIFFICULTY: dict[str, int] = {
    "boil":        1,
    "toast":       1,
    "steam":       1,
    "blend":       1,
    "whisk":       2,
    "fry":         2,
    "grill":       2,
    "bake":        2,
    "roast":       2,
    "simmer":      2,
    "sauté":       2,
    "marinate":    2,
    "fold":        2,
    "reduce":      3,
    "poach":       3,
    "braise":      3,
    "caramelise":  3,
    "knead":       3,
    "smoke":       4,
    "ferment":     5,
}

# Hard techniques used in difficulty scoring
HARD_TECHNIQUES: frozenset[str] = frozenset({
    "braise", "ferment", "smoke", "caramelise",
    "reduce", "poach", "knead", "fold",
})

# ---------------------------------------------------------------------------
# Technique → texture tag mapping
# ---------------------------------------------------------------------------

TECHNIQUE_TO_TEXTURE: dict[str, str] = {
    "fry":         "crispy",
    "grill":       "charred",
    "roast":       "crispy",
    "bake":        "flaky",
    "steam":       "silky",
    "braise":      "tender",
    "simmer":      "tender",
    "poach":       "tender",
    "whisk":       "fluffy",
    "blend":       "smooth",
    "toast":       "crunchy",
    "caramelise":  "sticky",
    "knead":       "chewy",
}


# ---------------------------------------------------------------------------
# Extraction functions
# ---------------------------------------------------------------------------

def extract_techniques_from_text(text: str) -> list[str]:
    """
    Extract all cooking technique tags from a text string.

    Args:
        text: Step instruction text, e.g. "Sauté the onions until golden brown."

    Returns:
        List of technique tag strings (deduplicated, sorted).
    """
    found = set()
    for technique, pattern in TECHNIQUE_PATTERNS.items():
        if pattern.search(text):
            found.add(technique)
    return sorted(found)


def extract_techniques_from_steps(steps: Sequence[str]) -> list[list[str]]:
    """
    Extract technique tags for each step in a recipe.

    Args:
        steps: List of step instruction strings.

    Returns:
        List of technique tag lists, one per step.
    """
    return [extract_techniques_from_text(step) for step in steps]


def recipe_technique_set(steps: Sequence[str]) -> set[str]:
    """
    Get the full set of unique techniques used across all steps.
    """
    techniques = set()
    for step in steps:
        techniques.update(extract_techniques_from_text(step))
    return techniques


def infer_textures_from_techniques(techniques: set[str]) -> list[str]:
    """
    Derive texture tags from the set of cooking techniques used.

    Returns:
        Deduplicated list of texture tag strings.
    """
    textures = set()
    for tech in techniques:
        if tech in TECHNIQUE_TO_TEXTURE:
            textures.add(TECHNIQUE_TO_TEXTURE[tech])
    return sorted(textures)


def max_technique_difficulty(techniques: set[str]) -> int:
    """
    Return the highest difficulty rating among the detected techniques.
    Returns 1 if no techniques found.
    """
    if not techniques:
        return 1
    return max(TECHNIQUE_DIFFICULTY.get(t, 2) for t in techniques)
