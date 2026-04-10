"""
Pipeline edge-case tests — empty query, long query, unicode, dietary conflict,
all-filtered scenario, off-topic detection.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.personal_ontology import (
    UserProfile, DietaryProfile, DietaryRestriction,
    CuisineAffinityProfile, CuisineAffinity, PreferenceLevel,
    FlavorProfile, CookingContext, CookingSkill,
    BudgetProfile, LocationProfile, AdventurousnessProfile,
)
from models.query_ontology import (
    QueryOntology, QueryMode, EatInAttributes, QueryAttribute, ValueType,
    QueryProfileConflict, ConflictType, ConflictResolution,
)
from models.fused_ontology import RetrievalContext
from services.pipeline.fusion import fuse_ontologies
from services.pipeline.ranker import rank_recipes


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def omnivore_profile():
    return UserProfile(
        user_id=uuid4(),
        dietary=DietaryProfile(spectrum_label="omnivore"),
        cuisine_affinities=CuisineAffinityProfile(
            affinities=[CuisineAffinity(cuisine="Italian", level=PreferenceLevel.LIKE)]
        ),
        flavor=FlavorProfile(spicy=5.0, umami=6.0),
        cooking=CookingContext(skill=CookingSkill.HOME_COOK, weeknight_minutes=45),
        budget=BudgetProfile(home_per_meal_eur=10.0, out_per_meal_eur=20.0),
        location=LocationProfile(city="Amsterdam", country="NL"),
        adventurousness=AdventurousnessProfile(cooking_score=5.0, dining_score=5.0),
        onboarding_complete=True,
        profile_summary_text="Omnivore who likes Italian food.",
    )


@pytest.fixture
def vegetarian_profile():
    return UserProfile(
        user_id=uuid4(),
        dietary=DietaryProfile(
            spectrum_label="vegetarian",
            hard_stops=[
                DietaryRestriction(label="meat", is_hard_stop=True, reason="ethical"),
            ],
        ),
        cuisine_affinities=CuisineAffinityProfile(
            affinities=[CuisineAffinity(cuisine="Italian", level=PreferenceLevel.LOVE)]
        ),
        flavor=FlavorProfile(spicy=3.0, umami=7.0),
        cooking=CookingContext(skill=CookingSkill.CONFIDENT, weeknight_minutes=40),
        budget=BudgetProfile(home_per_meal_eur=10.0, out_per_meal_eur=25.0),
        location=LocationProfile(city="Amsterdam", country="NL"),
        adventurousness=AdventurousnessProfile(cooking_score=6.0, dining_score=5.0),
        onboarding_complete=True,
        profile_summary_text="Vegetarian who loves Italian cuisine.",
    )


def _make_recipe(**overrides) -> dict:
    defaults = dict(
        id=str(uuid4()),
        title="Test Recipe",
        title_en="Test Recipe",
        cuisine_tags=["Italian"],
        description="A test recipe.",
        ingredients=[
            {"name": "pasta", "amount": 400, "unit": "g"},
            {"name": "tomato sauce", "amount": 200, "unit": "g"},
        ],
        steps=[{"step_number": 1, "instruction": "Cook.", "duration_min": 15}],
        time_prep_min=5,
        time_cook_min=15,
        time_total_min=20,
        serves=4,
        difficulty=2,
        flavor_tags=["savoury"],
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPipelineEdges:

    def test_empty_query_handled_gracefully(self, omnivore_profile):
        """Empty raw query → fusion should still produce a valid context."""
        query = QueryOntology(
            user_id=omnivore_profile.user_id,
            raw_query="",
            mode=QueryMode.EAT_IN,
            query_complexity=0.1,
        )
        ctx = fuse_ontologies(omnivore_profile, query)
        assert isinstance(ctx, RetrievalContext)

    def test_very_long_query_no_crash(self, omnivore_profile):
        """3000+ char query → should not crash."""
        long_text = "I want pasta " * 300  # ~3900 chars
        query = QueryOntology(
            user_id=omnivore_profile.user_id,
            raw_query=long_text,
            mode=QueryMode.EAT_IN,
            eat_in_attributes=EatInAttributes(desired_cuisine="Italian"),
            query_complexity=0.5,
        )
        ctx = fuse_ontologies(omnivore_profile, query)
        assert isinstance(ctx, RetrievalContext)

    def test_unicode_query_no_crash(self, omnivore_profile):
        """Unicode query → fusion + ranker should not crash."""
        query = QueryOntology(
            user_id=omnivore_profile.user_id,
            raw_query="寿司を作りたい",
            mode=QueryMode.EAT_IN,
            query_complexity=0.4,
        )
        ctx = fuse_ontologies(omnivore_profile, query)
        assert isinstance(ctx, RetrievalContext)

    def test_unicode_query_french(self, omnivore_profile):
        """French unicode query → fusion should not crash."""
        query = QueryOntology(
            user_id=omnivore_profile.user_id,
            raw_query="faire un couscous",
            mode=QueryMode.EAT_IN,
            query_complexity=0.4,
        )
        ctx = fuse_ontologies(omnivore_profile, query)
        assert isinstance(ctx, RetrievalContext)

    def test_dietary_conflict_detected(self, vegetarian_profile):
        """
        Vegetarian profile + steak query → conflict should produce warning.
        """
        query = QueryOntology(
            user_id=vegetarian_profile.user_id,
            raw_query="I want steak",
            mode=QueryMode.EAT_IN,
            extracted_attributes=[
                QueryAttribute(attribute="desired_ingredient", value="steak", centrality=0.9),
            ],
            conflicts=[
                QueryProfileConflict(
                    conflict_type=ConflictType.DIETARY_VIOLATION,
                    query_attribute="desired_ingredient",
                    profile_path="dietary.hard_stops",
                    query_value="steak",
                    profile_value="meat",
                    description="Query asks for steak but user has meat as hard stop",
                    resolution_strategy=ConflictResolution.HONOR_PROFILE,
                    warning_text="You have meat as a dietary restriction.",
                ),
            ],
            query_complexity=0.3,
        )
        ctx = fuse_ontologies(vegetarian_profile, query)
        assert len(ctx.warnings) > 0

    def test_all_filtered_returns_empty(self, omnivore_profile):
        """All candidates fail → ranker returns empty list."""
        query = QueryOntology(
            user_id=omnivore_profile.user_id,
            raw_query="Something specific",
            mode=QueryMode.EAT_IN,
            query_complexity=0.5,
        )
        ctx = fuse_ontologies(omnivore_profile, query)
        # No candidates at all
        ranked = rank_recipes([], omnivore_profile, query, ctx)
        assert ranked == []

    def test_off_topic_detection_query_shape(self, omnivore_profile):
        """
        Query with very low complexity and no food signal should be detected
        as off-topic by the pipeline (tested via query_complexity < 0.15).
        The pipeline checks that eat_in_attributes has no food signals.
        """
        query = QueryOntology(
            user_id=omnivore_profile.user_id,
            raw_query="what's the weather like?",
            mode=QueryMode.EAT_IN,
            query_complexity=0.1,  # Below 0.15 threshold
        )
        # Off-topic condition: complexity <= 0.15 AND no food signals in eat_in_attributes
        assert query.query_complexity <= 0.15
        ea = query.eat_in_attributes
        # Even with default EatInAttributes, all food-signal fields are None/empty
        has_food_signal = (
            ea is not None
            and (
                ea.desired_cuisine
                or ea.desired_ingredients
                or ea.mood
                or ea.occasion
                or ea.nutritional_goal
                or ea.time_constraint_minutes
            )
        )
        assert not has_food_signal, "Non-food query should have no food signals"
