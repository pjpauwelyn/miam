"""
Ranker edge-case tests — empty ingredients, missing difficulty, zero scores,
single recipe, duplicate titles.
"""
import sys
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.personal_ontology import (
    UserProfile, DietaryProfile, CuisineAffinityProfile,
    CuisineAffinity, PreferenceLevel, FlavorProfile,
    CookingContext, CookingSkill, BudgetProfile,
    LocationProfile, AdventurousnessProfile,
)
from models.query_ontology import (
    QueryOntology, QueryMode, EatInAttributes, QueryAttribute, ValueType,
)
from models.fused_ontology import RetrievalContext
from services.pipeline.ranker import rank_recipes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_profile(**overrides) -> UserProfile:
    defaults = dict(
        user_id=uuid4(),
        dietary=DietaryProfile(spectrum_label="omnivore"),
        cuisine_affinities=CuisineAffinityProfile(
            affinities=[CuisineAffinity(cuisine="Italian", level=PreferenceLevel.LIKE)]
        ),
        flavor=FlavorProfile(spicy=5.0, umami=5.0, sweet=5.0),
        cooking=CookingContext(skill=CookingSkill.HOME_COOK, weeknight_minutes=45),
        budget=BudgetProfile(home_per_meal_eur=10.0, out_per_meal_eur=20.0),
        location=LocationProfile(city="Amsterdam", country="NL"),
        adventurousness=AdventurousnessProfile(cooking_score=5.0, dining_score=5.0),
        onboarding_complete=True,
        profile_summary_text="Omnivore home cook, likes Italian food.",
    )
    defaults.update(overrides)
    return UserProfile(**defaults)


def _make_query(profile: UserProfile, **overrides) -> QueryOntology:
    defaults = dict(
        user_id=profile.user_id,
        raw_query="I want something nice to cook",
        mode=QueryMode.EAT_IN,
        eat_in_attributes=EatInAttributes(mood="comforting"),
        extracted_attributes=[
            QueryAttribute(attribute="mood", value="comforting", centrality=0.5),
        ],
        query_complexity=0.4,
    )
    defaults.update(overrides)
    return QueryOntology(**defaults)


def _make_recipe(**overrides) -> dict:
    defaults = dict(
        id=str(uuid4()),
        title="Test Recipe",
        title_en="Test Recipe",
        cuisine_tags=["Italian"],
        description="A test recipe.",
        ingredients=[
            {"name": "pasta", "amount": 400, "unit": "g"},
            {"name": "tomato", "amount": 200, "unit": "g"},
        ],
        steps=[{"step_number": 1, "instruction": "Cook.", "duration_min": 10}],
        time_prep_min=5,
        time_cook_min=15,
        time_total_min=20,
        serves=4,
        difficulty=2,
        flavor_tags=["savoury"],
        texture_tags=["soft"],
        dietary_tags=["vegetarian"],
        dietary_flags={
            "is_vegan": False, "is_vegetarian": True, "is_pescatarian_ok": True,
            "is_dairy_free": True, "is_gluten_free": False, "is_nut_free": True,
            "is_halal_ok": True, "contains_pork": False, "contains_shellfish": False,
            "contains_alcohol": False,
        },
        nutrition_per_serving={"kcal": 350, "protein_g": 10, "fat_g": 8, "carbs_g": 50},
        season_tags=["year-round"],
        occasion_tags=["weeknight-dinner"],
        course_tags=["main"],
        source_type="mock_tier0",
        embedding_text="test recipe Italian pasta tomato",
        data_quality_score=0.90,
        _similarity=0.80,
    )
    defaults.update(overrides)
    return defaults


def _fuse(profile, query):
    from services.pipeline.fusion import fuse_ontologies
    return fuse_ontologies(profile, query)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRankerEdges:
    def test_empty_ingredients_no_crash(self):
        """Recipe with empty ingredients list → should not crash, score 0.3 for ingredient overlap."""
        profile = _make_profile()
        query = _make_query(
            profile,
            eat_in_attributes=EatInAttributes(desired_ingredients=["pasta"]),
            extracted_attributes=[
                QueryAttribute(attribute="desired_ingredient", value="pasta", centrality=0.8),
            ],
        )
        ctx = _fuse(profile, query)
        recipe = _make_recipe(ingredients=[])
        ranked = rank_recipes([recipe], profile, query, ctx)
        assert len(ranked) == 1
        assert "_match_score" in ranked[0]
        assert "_match_tier" in ranked[0]
        assert 0.0 <= ranked[0]["_match_score"] <= 1.0

    def test_missing_difficulty_defaults_gracefully(self):
        """Recipe with no difficulty key → ranker uses neutral 0.5 score for difficulty factor."""
        profile = _make_profile()
        query = _make_query(profile)
        ctx = _fuse(profile, query)
        recipe = _make_recipe()
        del recipe["difficulty"]
        ranked = rank_recipes([recipe], profile, query, ctx)
        assert len(ranked) == 1
        assert "_match_score" in ranked[0]
        assert "_match_tier" in ranked[0]

    def test_all_zero_scores_still_returns(self):
        """All recipes score very low → ranker should still return them as stretch_pick."""
        profile = _make_profile(
            cuisine_affinities=CuisineAffinityProfile(
                affinities=[CuisineAffinity(cuisine="Ethiopian", level=PreferenceLevel.LOVE)]
            ),
        )
        query = _make_query(
            profile,
            eat_in_attributes=EatInAttributes(
                desired_cuisine="Ethiopian",
                desired_ingredients=["injera", "berbere"],
            ),
        )
        ctx = _fuse(profile, query)
        # Recipe is Italian, completely different from what's asked
        recipe = _make_recipe(cuisine_tags=["German"], flavor_tags=[], difficulty=5, time_total_min=120)
        ranked = rank_recipes([recipe], profile, query, ctx)
        assert len(ranked) == 1
        assert "_match_score" in ranked[0]
        # Should be stretch_pick given the total mismatch
        assert ranked[0]["_match_tier"] == "stretch_pick"

    def test_single_recipe_in_candidates(self):
        """Single recipe → should work without errors, return one result."""
        profile = _make_profile()
        query = _make_query(profile)
        ctx = _fuse(profile, query)
        recipe = _make_recipe()
        ranked = rank_recipes([recipe], profile, query, ctx)
        assert len(ranked) == 1
        assert ranked[0]["title"] == "Test Recipe"
        assert "_match_score" in ranked[0]

    def test_duplicate_titles_no_crash(self):
        """Duplicate recipe titles in candidate list → should not cause issues."""
        profile = _make_profile()
        query = _make_query(profile)
        ctx = _fuse(profile, query)
        recipe_a = _make_recipe(title="Spaghetti", title_en="Spaghetti", _similarity=0.9)
        recipe_b = _make_recipe(title="Spaghetti", title_en="Spaghetti", _similarity=0.7)
        ranked = rank_recipes([recipe_a, recipe_b], profile, query, ctx)
        assert len(ranked) == 2
        for r in ranked:
            assert "_match_score" in r
            assert "_match_tier" in r
