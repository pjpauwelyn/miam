"""
Stage 4: Ranker

Multi-factor weighted ranking of retrieved recipe candidates against the
user profile and query ontology. Pure Python, no LLM.

Function signature:
    def rank_recipes(
        recipes: list[dict],
        profile: UserProfile,
        query: QueryOntology,
        retrieval_context: RetrievalContext,
    ) -> list[dict]

7 ranking factors:
  1. Ingredient overlap (Jaccard)          weight=0.30
  2. Dietary compliance                    weight=0.25
  3. Cuisine affinity                      weight=0.15
  4. Difficulty match                      weight=0.10
  5. Time fit                              weight=0.10
  6. Flavor affinity                       weight=0.05
  7. Novelty bonus                         weight=0.05

Match tier labels:
  full_match   >= 0.80
  close_match  0.50 - 0.79
  stretch_pick 0.30 - 0.49
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
from services.synonym_resolver import normalize_ingredient as _resolve_synonym

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Factor weights (must sum to 1.0)
# ---------------------------------------------------------------------------
FACTOR_WEIGHTS = {
    "ingredient_overlap":  0.30,
    "dietary_compliance":  0.25,
    "cuisine_affinity":    0.15,
    "difficulty_match":    0.10,
    "time_fit":            0.10,
    "flavor_affinity":     0.05,
    "novelty_bonus":       0.05,
}

assert abs(sum(FACTOR_WEIGHTS.values()) - 1.0) < 1e-9, "Factor weights must sum to 1.0"

# Match tier thresholds
TIER_FULL_MATCH    = 0.80
TIER_CLOSE_MATCH   = 0.50
TIER_STRETCH_PICK  = 0.30

# Cooking skill -> difficulty ceiling (recipe difficulty 1-5)
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
# Helper: normalize ingredient name through EU/US synonym resolver
# ---------------------------------------------------------------------------

def _normalize_ingredient(name: str) -> str:
    """
    Normalize an ingredient name to its EU/British English canonical form
    via the synonym resolver, so that e.g. "eggplant" and "aubergine"
    are treated as the same ingredient during overlap scoring.
    """
    return _resolve_synonym(name.lower().strip())


# ---------------------------------------------------------------------------
# Helper: extract ingredient names from a recipe
# ---------------------------------------------------------------------------

def _get_recipe_ingredient_names(recipe: dict) -> set[str]:
    """Extract and normalize ingredient names from a recipe dict."""
    names: set[str] = set()
    for ing in (recipe.get("ingredients") or []):
        if isinstance(ing, dict):
            name = (ing.get("name") or "").lower().strip()
        elif isinstance(ing, str):
            name = ing.lower().strip()
        else:
            continue
        if name:
            names.add(_normalize_ingredient(name))
    return names


# ---------------------------------------------------------------------------
# Factor 1: Ingredient overlap (Jaccard similarity)
# ---------------------------------------------------------------------------

def _score_ingredient_overlap(
    recipe: dict,
    desired_ingredients: list[str],
    excluded_ingredients: list[str],
) -> float:
    """
    Measures how well the recipe's ingredients match the desired ingredients.
    Returns 0.0-1.0.

    If desired_ingredients is empty, returns 0.5 (neutral).
    Excluded ingredients create a penalty.

    Both query ingredients and recipe ingredients are normalized through the
    synonym resolver before comparison, so "eggplant" matches "aubergine" etc.
    """
    if not desired_ingredients:
        return 0.5  # no preference expressed -> neutral

    recipe_ings = _get_recipe_ingredient_names(recipe)
    if not recipe_ings:
        return 0.3  # recipe has no ingredients data -> below neutral

    desired_set = {_normalize_ingredient(i) for i in desired_ingredients}

    # Check for substring matches (e.g. "chicken" in "chicken breast")
    overlap = 0
    for desired in desired_set:
        for recipe_ing in recipe_ings:
            if desired in recipe_ing or recipe_ing in desired:
                overlap += 1
                break

    # Jaccard over desired ingredients (what fraction of desired are in the recipe)
    jaccard = overlap / len(desired_set)

    # Penalty for excluded ingredients present in recipe
    excluded_set = {_normalize_ingredient(i) for i in excluded_ingredients}
    excluded_hit = any(
        exc in recipe_ing or recipe_ing in exc
        for exc in excluded_set
        for recipe_ing in recipe_ings
    )
    if excluded_hit:
        jaccard = max(0.0, jaccard - 0.5)

    return min(1.0, jaccard)


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
        # Pydantic model -- convert to dict
        try:
            dietary_flags = dietary_flags.model_dump()
        except AttributeError:
            dietary_flags = {}

    score = 1.0

    # Hard stops -- any violation -> 0.0
    for restriction in profile.dietary.hard_stops:
        if not restriction.is_hard_stop:
            continue
        label = _normalize_ingredient(restriction.label)

        # Check dietary flags (e.g. "pork" -> contains_pork)
        flag_key = f"contains_{restriction.label.lower()}"
        if dietary_flags.get(flag_key) is True:
            return 0.0

        # Check in ingredient names
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

    # Soft stops -- penalty
    for restriction in profile.dietary.soft_stops:
        label = _normalize_ingredient(restriction.label)
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
    Returns 0.0-1.0.

    If the query explicitly requested a cuisine, that cuisine gets a 1.0 score.
    """
    recipe_cuisines = [c.lower() for c in (recipe.get("cuisine_tags") or [])]
    if not recipe_cuisines:
        return 0.5  # no cuisine data -> neutral

    ea = query.eat_in_attributes
    if ea and ea.desired_cuisine:
        desired_lower = ea.desired_cuisine.lower()
        if any(desired_lower in rc or rc in desired_lower for rc in recipe_cuisines):
            return 1.0
        # Different cuisine from what was asked
        return 0.2

    # Match against profile affinities
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
        # Exact or substring match
        for aff_cuisine, aff_score in affinity_map.items():
            if aff_cuisine in rc or rc in aff_cuisine:
                matched_scores.append(aff_score)
                break

    if not matched_scores:
        return 0.5  # no match found -> neutral

    return sum(matched_scores) / len(matched_scores)


# ---------------------------------------------------------------------------
# Factor 4: Difficulty match
# ---------------------------------------------------------------------------

def _score_difficulty_match(recipe: dict, profile: UserProfile, query: QueryOntology) -> float:
    """
    Compares recipe difficulty (1-5) against user skill level.
    Returns 1.0 if recipe is within the user's comfort zone.
    """
    recipe_difficulty = recipe.get("difficulty")
    if recipe_difficulty is None:
        return 0.5  # no data -> neutral

    try:
        recipe_difficulty = int(recipe_difficulty)
    except (TypeError, ValueError):
        return 0.5

    # Query-explicit difficulty constraint
    ea = query.eat_in_attributes
    if ea and ea.difficulty_constraint:
        constraint_map = {"easy": (1, 2), "medium": (2, 3), "challenging": (4, 5)}
        low, high = constraint_map.get(ea.difficulty_constraint, (1, 5))
        if low <= recipe_difficulty <= high:
            return 1.0
        diff = min(abs(recipe_difficulty - low), abs(recipe_difficulty - high))
        return max(0.0, 1.0 - diff * 0.25)

    # Profile skill ceiling
    skill_ceiling = SKILL_DIFFICULTY_MAP.get(profile.cooking.skill, 3)

    if recipe_difficulty <= skill_ceiling:
        # Within skill level -- score based on how well it matches (not too easy)
        gap = skill_ceiling - recipe_difficulty
        return 1.0 - (gap * 0.1)  # slight preference for near-ceiling recipes
    else:
        # Above skill level -- penalty scales with how far above
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
        # Well within budget -- proportional score
        ratio = recipe_time / limit if limit > 0 else 1.0
        # Slightly reward recipes that use most of the budget (more interesting)
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
    Returns 0.0-1.0.
    """
    recipe_flavors = [f.lower() for f in (recipe.get("flavor_tags") or [])]
    if not recipe_flavors:
        return 0.5  # no flavor data -> neutral

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
        # Common recipe tags -> flavor map
        "acidic": None,  # maps to sour
        "rich":   None,  # maps to fatty
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
        # Normalize tag to our flavor dimensions
        flavor_dim = tag if tag in flavor_map else tag_to_flavor.get(tag)
        if flavor_dim and flavor_map.get(flavor_dim) is not None:
            pref = flavor_map[flavor_dim]  # 0-10
            # Recipe tag present -> the recipe HAS this flavor
            # Score: 1.0 if pref high (>=7), 0.5 neutral, 0.0 if pref very low (<=2)
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
    Returns 0.0-1.0.

    Scoring intent:
    - LOW adventurousness + familiar cuisine  -> high score  (comfort zone = good)
    - HIGH adventurousness + unfamiliar cuisine -> high score  (exploration = good)
    - LOW adventurousness + unfamiliar cuisine  -> low score   (too risky)
    - HIGH adventurousness + familiar cuisine   -> medium score (fine but boring)

    Implementation:
    - rare cuisine + high adventurousness  -> 0.5 + 0.5 * adv  (peaks at 1.0)
    - rare cuisine + low adventurousness   -> 0.5 + 0.5 * adv  (bottoms at 0.5)
    - common cuisine + high adventurousness -> 0.5 + 0.25 * (1 - adv) (medium-low)
    - common cuisine + low adventurousness  -> 0.5 + 0.25 * (1 - adv) (peaks at 0.75)
    This correctly rewards conservative users for common cuisines and adventurous
    users for rare cuisines, while penalizing conservative users for rare cuisines
    relative to adventurous users.
    """
    recipe_cuisines = {c.lower() for c in (recipe.get("cuisine_tags") or [])}
    if not recipe_cuisines:
        return 0.5

    # Is this a "rare" cuisine?
    is_rare = not recipe_cuisines.intersection(_COMMON_CUISINES)
    adventurousness = profile.adventurousness.cooking_score / 10.0  # normalize 0-1

    if is_rare:
        # Adventurous users get a bonus; conservative users get a slight penalty
        # relative to adventurous users, but score still floors at 0.5.
        return 0.5 + 0.5 * adventurousness
    else:
        # Common cuisine: conservative users get a slight comfort bonus;
        # adventurous users get slightly less (they want variety).
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
            # Compute each factor (0.0-1.0)
            f_ingredient   = _score_ingredient_overlap(recipe, desired_ingredients, excluded_ingredients)
            f_dietary      = _score_dietary_compliance(recipe, profile)
            f_cuisine      = _score_cuisine_affinity(recipe, profile, query)
            f_difficulty   = _score_difficulty_match(recipe, profile, query)
            f_time         = _score_time_fit(recipe, profile, query)
            f_flavor       = _score_flavor_affinity(recipe, profile)
            f_novelty      = _score_novelty_bonus(recipe, profile)

            # Dietary compliance is a gate: 0.0 -> still rank but last
            # (hard filter already removed true violations in Stage 3)
            composite = (
                FACTOR_WEIGHTS["ingredient_overlap"]  * f_ingredient
                + FACTOR_WEIGHTS["dietary_compliance"] * f_dietary
                + FACTOR_WEIGHTS["cuisine_affinity"]   * f_cuisine
                + FACTOR_WEIGHTS["difficulty_match"]   * f_difficulty
                + FACTOR_WEIGHTS["time_fit"]           * f_time
                + FACTOR_WEIGHTS["flavor_affinity"]    * f_flavor
                + FACTOR_WEIGHTS["novelty_bonus"]      * f_novelty
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
                "ingredient_overlap":  round(f_ingredient, 3),
                "dietary_compliance":  round(f_dietary, 3),
                "cuisine_affinity":    round(f_cuisine, 3),
                "difficulty_match":    round(f_difficulty, 3),
                "time_fit":            round(f_time, 3),
                "flavor_affinity":     round(f_flavor, 3),
                "novelty_bonus":       round(f_novelty, 3),
            }

            scored_recipes.append(ranked)

        except Exception as exc:
            logger.warning(
                "Ranking error for recipe %s: %s",
                recipe.get("_entity_id", "?"),
                exc,
            )
            # Include with a low score so it isn't silently dropped
            fallback = dict(recipe)
            fallback["_match_score"] = 0.1
            fallback["_match_tier"] = "stretch_pick"
            fallback["_factor_scores"] = {}
            scored_recipes.append(fallback)

    # Sort by composite score descending
    scored_recipes.sort(key=lambda r: r.get("_match_score", 0.0), reverse=True)

    top = scored_recipes[:top_n]

    logger.info(
        "Stage 4 complete: ranked %d -> returning top %d "
        "(scores: %s)",
        len(scored_recipes),
        len(top),
        [r["_match_score"] for r in top],
    )

    return top
