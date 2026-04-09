"""
Stage 4: Ranker (Experiment B)

Multi-factor weighted ranking of retrieved recipe candidates against the
user profile and query ontology. Pure Python, no LLM.

EXPERIMENT B CHANGES vs main:
  - Added 8th factor: embedding_similarity (weight=0.20)
    Preserves the semantic signal from Stage 3 (_similarity key)
    instead of discarding it after retrieval.
  - Rebalanced weights: ingredient_overlap reduced from 0.30 → 0.18
    to stop it dominating the composite score.
  - Upgraded _score_ingredient_overlap: token-level matching replaces
    coarse full-string Jaccard, giving partial credit for multi-word
    ingredient names and core-token matches.

Function signature (unchanged):
    def rank_recipes(
        recipes: list[dict],
        profile: UserProfile,
        query: QueryOntology,
        retrieval_context: RetrievalContext,
        top_n: int = 5,
    ) -> list[dict]

8 ranking factors:
  0. Embedding similarity (Stage 3 semantic signal)  weight=0.20  [NEW]
  1. Ingredient overlap (token-level)                weight=0.18  [CHANGED from 0.30]
  2. Dietary compliance                              weight=0.22  [CHANGED from 0.25]
  3. Cuisine affinity                                weight=0.15
  4. Difficulty match                                weight=0.08  [CHANGED from 0.10]
  5. Time fit                                        weight=0.08  [CHANGED from 0.10]
  6. Flavor affinity                                 weight=0.05
  7. Novelty bonus                                   weight=0.04  [CHANGED from 0.05]

Match tier labels:
  full_match   >= 0.80
  close_match  0.50 – 0.79
  stretch_pick 0.30 – 0.49
  (below 0.30: still returned if needed, labelled stretch_pick)
"""
from __future__ import annotations

import logging
from typing import Any

from models.fused_ontology import RetrievalContext
from models.personal_ontology import (
    CookingSkill,
    PreferenceLevel,
    UserProfile,
)
from models.query_ontology import QueryOntology

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Factor weights (must sum to 1.0)
# ---------------------------------------------------------------------------
FACTOR_WEIGHTS = {
    "embedding_similarity": 0.20,   # NEW — Stage 3 semantic signal preserved
    "ingredient_overlap":   0.18,   # reduced — was over-dominant at 0.30
    "dietary_compliance":   0.22,   # slightly reduced but still high-priority gate
    "cuisine_affinity":     0.15,   # unchanged
    "difficulty_match":     0.08,   # slightly reduced
    "time_fit":             0.08,   # slightly reduced
    "flavor_affinity":      0.05,   # unchanged
    "novelty_bonus":        0.04,   # slightly reduced
}

assert abs(sum(FACTOR_WEIGHTS.values()) - 1.0) < 1e-9, "Factor weights must sum to 1.0"

# Match tier thresholds
TIER_FULL_MATCH    = 0.80
TIER_CLOSE_MATCH   = 0.50
TIER_STRETCH_PICK  = 0.30

# Cooking skill → difficulty ceiling (recipe difficulty 1–5)
SKILL_DIFFICULTY_MAP: dict[CookingSkill, int] = {
    CookingSkill.BEGINNER:     1,
    CookingSkill.HOME_COOK:    2,
    CookingSkill.CONFIDENT:    3,
    CookingSkill.ADVANCED:     4,
    CookingSkill.PROFESSIONAL: 5,
}

# Common cuisines (for novelty bonus computation)
_COMMON_CUISINES = {
    "italian", "french", "chinese", "mexican", "indian",
    "japanese", "american", "british", "spanish", "greek",
    "thai", "turkish", "mediterranean",
}


# ---------------------------------------------------------------------------
# Helper: extract ingredient names from a recipe
# ---------------------------------------------------------------------------

def _get_recipe_ingredient_names(recipe: dict) -> set[str]:
    """Extract ingredient names from a recipe dict as a lowercase set."""
    names: set[str] = set()
    for ing in (recipe.get("ingredients") or []):
        if isinstance(ing, dict):
            name = (ing.get("name") or "").lower().strip()
        elif isinstance(ing, str):
            name = ing.lower().strip()
        else:
            continue
        if name:
            names.add(name)
    return names


def _normalize_ingredient(name: str) -> str:
    """Basic normalization: lowercase, strip, remove common quantifiers."""
    return name.lower().strip()


# ---------------------------------------------------------------------------
# Factor 0 (NEW): Embedding similarity — preserve Stage 3 semantic signal
# ---------------------------------------------------------------------------

def _score_embedding_similarity(recipe: dict) -> float:
    """
    Factor 0: Embedding similarity from Stage 3.

    The retriever already computed cosine similarity and stored it as _similarity.
    We pass it through as a ranking signal so semantic relevance isn't discarded
    after the retrieval stage.

    Returns 0.0–1.0. If _similarity is absent, returns 0.5 (neutral).
    """
    sim = recipe.get("_similarity")
    if sim is None:
        return 0.5  # no data → neutral
    # Clamp to [0, 1] — cosine similarity can be negative for unrelated vectors
    return max(0.0, min(1.0, float(sim)))


# ---------------------------------------------------------------------------
# Factor 1: Ingredient overlap (token-level matching)
# ---------------------------------------------------------------------------

def _score_ingredient_overlap(
    recipe: dict,
    desired_ingredients: list[str],
    excluded_ingredients: list[str],
) -> float:
    """
    Measures how well the recipe's ingredients match the desired ingredients.

    EXPERIMENT B UPGRADE: Uses token-level matching instead of full-string
    Jaccard. Splits ingredient names into words and checks for token overlap.
    This is more precise: "chicken breast" correctly matches "chicken" without
    false-positives from unrelated substring matches.

    Returns 0.0–1.0. If desired_ingredients is empty, returns 0.5 (neutral).
    """
    if not desired_ingredients:
        return 0.5  # no preference expressed → neutral

    recipe_ings = _get_recipe_ingredient_names(recipe)
    if not recipe_ings:
        return 0.3  # recipe has no ingredients data → below neutral

    # Tokenize each recipe ingredient into word sets
    recipe_tokens_per_ing: list[set[str]] = []
    all_recipe_tokens: set[str] = set()
    for ing in recipe_ings:
        tokens = set(ing.lower().split())
        recipe_tokens_per_ing.append(tokens)
        all_recipe_tokens.update(tokens)

    desired_set = {_normalize_ingredient(i) for i in desired_ingredients}

    # Score each desired ingredient
    overlap: float = 0.0
    for desired in desired_set:
        desired_tokens = set(desired.lower().split())
        matched = False
        for recipe_tokens in recipe_tokens_per_ing:
            # Full subset match in either direction
            if desired_tokens.issubset(recipe_tokens) or recipe_tokens.issubset(desired_tokens):
                overlap += 1.0
                matched = True
                break
        if not matched:
            # Partial credit: core token (longest word) present anywhere in recipe
            if desired_tokens:
                core_token = max(desired_tokens, key=len)
                if len(core_token) >= 3 and core_token in all_recipe_tokens:
                    overlap += 0.7

    score = overlap / len(desired_set)

    # Penalty for excluded ingredients present in recipe
    excluded_set = {_normalize_ingredient(i) for i in excluded_ingredients}
    for exc in excluded_set:
        exc_tokens = set(exc.lower().split())
        if exc_tokens:
            core_exc = max(exc_tokens, key=len)
            if len(core_exc) >= 3 and core_exc in all_recipe_tokens:
                score = max(0.0, score - 0.5)
                break

    return min(1.0, score)


# ---------------------------------------------------------------------------
# Factor 2: Dietary compliance
# ---------------------------------------------------------------------------

def _score_dietary_compliance(recipe: dict, profile: UserProfile) -> float:
    """
    Checks whether the recipe satisfies the user's dietary hard and soft stops.
    Returns 1.0 (perfect compliance) to 0.0 (hard stop violated).
    """
    recipe_ings = _get_recipe_ingredient_names(recipe)
    dietary_flags = recipe.get("dietary_flags") or {}
    if not isinstance(dietary_flags, dict):
        try:
            dietary_flags = dietary_flags.model_dump()
        except AttributeError:
            dietary_flags = {}

    score = 1.0

    # Hard stops — any violation → 0.0
    for restriction in profile.dietary.hard_stops:
        if not restriction.is_hard_stop:
            continue
        label = restriction.label.lower()

        flag_key = f"contains_{label}"
        if dietary_flags.get(flag_key) is True:
            return 0.0

        for ing_name in recipe_ings:
            if label in ing_name:
                return 0.0

    # Spectrum-based checks
    spectrum = (profile.dietary.spectrum_label or "").lower()
    if "vegan" in spectrum and "flexitarian" not in spectrum:
        if not dietary_flags.get("is_vegan", False):
            return 0.0
    elif "vegetarian" in spectrum:
        if not dietary_flags.get("is_vegetarian", False):
            return 0.0

    # Soft stops — penalty
    for restriction in profile.dietary.soft_stops:
        label = restriction.label.lower()
        for ing_name in recipe_ings:
            if label in ing_name:
                score = max(0.0, score - 0.3)
                break

    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Factor 3: Cuisine affinity
# ---------------------------------------------------------------------------

def _score_cuisine_affinity(recipe: dict, profile: UserProfile, query: QueryOntology) -> float:
    """
    Matches the recipe's cuisine_tags against the user's cuisine affinities.
    Returns 0.0–1.0.

    If the query explicitly requested a cuisine, that cuisine gets a 1.0 score.
    """
    recipe_cuisines = [c.lower() for c in (recipe.get("cuisine_tags") or [])]
    if not recipe_cuisines:
        return 0.5

    ea = query.eat_in_attributes
    if ea and ea.desired_cuisine:
        desired_lower = ea.desired_cuisine.lower()
        if any(desired_lower in rc or rc in desired_lower for rc in recipe_cuisines):
            return 1.0
        return 0.2

    affinity_map: dict[str, float] = {}
    for aff in profile.cuisine_affinities.affinities:
        level_score = {
            PreferenceLevel.LOVE:    1.0,
            PreferenceLevel.LIKE:    0.75,
            PreferenceLevel.NEUTRAL: 0.5,
            PreferenceLevel.DISLIKE: 0.15,
            PreferenceLevel.NEVER:   0.0,
        }.get(aff.level, 0.5)
        affinity_map[aff.cuisine.lower()] = level_score

    matched_scores = []
    for rc in recipe_cuisines:
        for aff_cuisine, aff_score in affinity_map.items():
            if aff_cuisine in rc or rc in aff_cuisine:
                matched_scores.append(aff_score)
                break

    if not matched_scores:
        return 0.5

    return sum(matched_scores) / len(matched_scores)


# ---------------------------------------------------------------------------
# Factor 4: Difficulty match
# ---------------------------------------------------------------------------

def _score_difficulty_match(recipe: dict, profile: UserProfile, query: QueryOntology) -> float:
    """
    Compares recipe difficulty (1–5) against user skill level.
    Returns 1.0 if recipe is within the user's comfort zone.
    """
    recipe_difficulty = recipe.get("difficulty")
    if recipe_difficulty is None:
        return 0.5

    try:
        recipe_difficulty = int(recipe_difficulty)
    except (TypeError, ValueError):
        return 0.5

    ea = query.eat_in_attributes
    if ea and ea.difficulty_constraint:
        constraint_map = {"easy": (1, 2), "medium": (2, 3), "challenging": (4, 5)}
        low, high = constraint_map.get(ea.difficulty_constraint, (1, 5))
        if low <= recipe_difficulty <= high:
            return 1.0
        diff = min(abs(recipe_difficulty - low), abs(recipe_difficulty - high))
        return max(0.0, 1.0 - diff * 0.25)

    skill_ceiling = SKILL_DIFFICULTY_MAP.get(profile.cooking.skill, 3)

    if recipe_difficulty <= skill_ceiling:
        gap = skill_ceiling - recipe_difficulty
        return 1.0 - (gap * 0.1)
    else:
        overshoot = recipe_difficulty - skill_ceiling
        return max(0.0, 1.0 - overshoot * 0.35)


# ---------------------------------------------------------------------------
# Factor 5: Time fit
# ---------------------------------------------------------------------------

def _score_time_fit(recipe: dict, profile: UserProfile, query: QueryOntology) -> float:
    """
    Compares recipe total time against the user's time budget.
    Returns 1.0 if recipe fits within time budget.
    """
    recipe_time = recipe.get("time_total_min")
    if recipe_time is None:
        return 0.5

    try:
        recipe_time = int(recipe_time)
    except (TypeError, ValueError):
        return 0.5

    ea = query.eat_in_attributes
    if ea and ea.time_constraint_minutes is not None:
        limit = ea.time_constraint_minutes
    else:
        limit = profile.cooking.weeknight_minutes

    if recipe_time <= limit:
        ratio = recipe_time / limit if limit > 0 else 1.0
        return 0.7 + 0.3 * ratio
    else:
        overshoot_ratio = (recipe_time - limit) / limit if limit > 0 else 1.0
        return max(0.0, 1.0 - overshoot_ratio * 0.8)


# ---------------------------------------------------------------------------
# Factor 6: Flavor affinity
# ---------------------------------------------------------------------------

def _score_flavor_affinity(recipe: dict, profile: UserProfile) -> float:
    """
    Compares recipe flavor_tags against the user's flavor preferences.
    Returns 0.0–1.0.
    """
    recipe_flavors = [f.lower() for f in (recipe.get("flavor_tags") or [])]
    if not recipe_flavors:
        return 0.5

    flavor_map = {
        "spicy":     profile.flavor.spicy,
        "sweet":     profile.flavor.sweet,
        "sour":      profile.flavor.sour,
        "umami":     profile.flavor.umami,
        "bitter":    profile.flavor.bitter,
        "fatty":     profile.flavor.fatty,
        "fermented": profile.flavor.fermented,
        "smoky":     profile.flavor.smoky,
        "salty":     profile.flavor.salty,
        "acidic": None,
        "rich":   None,
        "light":  None,
        "herbaceous": None,
    }

    tag_to_flavor = {
        "acidic": "sour",
        "rich": "fatty",
        "hot": "spicy",
        "peppery": "spicy",
        "briny": "salty",
        "caramelized": "sweet",
        "charred": "smoky",
        "grilled": "smoky",
        "pickled": "fermented",
        "fermented": "fermented",
        "savory": "umami",
        "meaty": "umami",
    }

    scores: list[float] = []
    for tag in recipe_flavors:
        flavor_dim = tag if tag in flavor_map else tag_to_flavor.get(tag)
        if flavor_dim and flavor_map.get(flavor_dim) is not None:
            pref = flavor_map[flavor_dim]
            normalized_pref = pref / 10.0
            if normalized_pref >= 0.7:
                scores.append(1.0)
            elif normalized_pref <= 0.2:
                scores.append(0.0)
            else:
                scores.append(normalized_pref)

    if not scores:
        return 0.5

    return sum(scores) / len(scores)


# ---------------------------------------------------------------------------
# Factor 7: Novelty bonus
# ---------------------------------------------------------------------------

def _score_novelty_bonus(recipe: dict, profile: UserProfile) -> float:
    """
    Small bonus for less-common cuisines, weighted by the user's adventurousness score.
    Returns 0.0–1.0.
    """
    recipe_cuisines = {c.lower() for c in (recipe.get("cuisine_tags") or [])}
    if not recipe_cuisines:
        return 0.5

    is_rare = not recipe_cuisines.intersection(_COMMON_CUISINES)
    adventurousness = profile.adventurousness.cooking_score / 10.0

    if is_rare:
        return 0.5 + 0.5 * adventurousness
    else:
        return 0.5 + 0.25 * (1.0 - adventurousness)


# ---------------------------------------------------------------------------
# Main ranking function
# ---------------------------------------------------------------------------

def rank_recipes(
    recipes: list[dict],
    profile: UserProfile,
    query: QueryOntology,
    retrieval_context: RetrievalContext,
    top_n: int = 5,
) -> list[dict]:
    """
    Stage 4: Multi-factor weighted ranking of retrieved recipes.

    Returns the top_n recipes sorted by composite _match_score,
    with _match_score and _match_tier added to each dict.

    Args:
        recipes: List of recipe dicts from Stage 3 (each has _similarity key).
        profile: User's personal ontology.
        query: Query ontology from Stage 1+2.
        retrieval_context: Fusion output from Stage 2b.
        top_n: Number of top recipes to return (default 5).

    Returns:
        Sorted list of recipe dicts (top_n entries) with scoring metadata.
    """
    if not recipes:
        return []

    ea = query.eat_in_attributes
    desired_ingredients = (ea.desired_ingredients if ea else []) or []
    excluded_ingredients = (ea.excluded_ingredients if ea else []) or []

    scored_recipes = []

    for recipe in recipes:
        try:
            # Compute each factor (0.0–1.0)
            f_embedding    = _score_embedding_similarity(recipe)                                  # [NEW]
            f_ingredient   = _score_ingredient_overlap(recipe, desired_ingredients, excluded_ingredients)
            f_dietary      = _score_dietary_compliance(recipe, profile)
            f_cuisine      = _score_cuisine_affinity(recipe, profile, query)
            f_difficulty   = _score_difficulty_match(recipe, profile, query)
            f_time         = _score_time_fit(recipe, profile, query)
            f_flavor       = _score_flavor_affinity(recipe, profile)
            f_novelty      = _score_novelty_bonus(recipe, profile)

            # Composite score (8 factors)
            composite = (
                FACTOR_WEIGHTS["embedding_similarity"] * f_embedding
                + FACTOR_WEIGHTS["ingredient_overlap"]  * f_ingredient
                + FACTOR_WEIGHTS["dietary_compliance"]  * f_dietary
                + FACTOR_WEIGHTS["cuisine_affinity"]    * f_cuisine
                + FACTOR_WEIGHTS["difficulty_match"]    * f_difficulty
                + FACTOR_WEIGHTS["time_fit"]            * f_time
                + FACTOR_WEIGHTS["flavor_affinity"]     * f_flavor
                + FACTOR_WEIGHTS["novelty_bonus"]       * f_novelty
            )

            # Assign tier label
            if composite >= TIER_FULL_MATCH:
                tier = "full_match"
            elif composite >= TIER_CLOSE_MATCH:
                tier = "close_match"
            else:
                tier = "stretch_pick"

            # Build augmented copy (shallow, avoid mutating original)
            ranked = dict(recipe)
            ranked["_match_score"] = round(composite, 4)
            ranked["_match_tier"] = tier
            ranked["_factor_scores"] = {
                "embedding_similarity": round(f_embedding, 3),   # [NEW]
                "ingredient_overlap":   round(f_ingredient, 3),
                "dietary_compliance":   round(f_dietary, 3),
                "cuisine_affinity":     round(f_cuisine, 3),
                "difficulty_match":     round(f_difficulty, 3),
                "time_fit":             round(f_time, 3),
                "flavor_affinity":      round(f_flavor, 3),
                "novelty_bonus":        round(f_novelty, 3),
            }

            scored_recipes.append(ranked)

        except Exception as exc:
            logger.warning(
                "Ranking error for recipe %s: %s",
                recipe.get("_entity_id", "?"),
                exc,
            )
            fallback = dict(recipe)
            fallback["_match_score"] = 0.1
            fallback["_match_tier"] = "stretch_pick"
            fallback["_factor_scores"] = {}
            scored_recipes.append(fallback)

    # Sort by composite score descending
    scored_recipes.sort(key=lambda r: r.get("_match_score", 0.0), reverse=True)

    top = scored_recipes[:top_n]

    logger.info(
        "Stage 4 (exp/b) complete: ranked %d → returning top %d "
        "(scores: %s)",
        len(scored_recipes),
        len(top),
        [r["_match_score"] for r in top],
    )

    return top
