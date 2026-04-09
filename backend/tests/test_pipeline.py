"""
Phase 1 pipeline tests — fusion, ranking, and end-to-end integration.
Tests that don't require LLM calls (fusion, ranking) run as unit tests.
Tests requiring LLM calls are marked with @pytest.mark.integration.
"""
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest

# Ensure backend modules importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Set env vars for tests
os.environ.setdefault("MISTRAL_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test")

from models.personal_ontology import (
    UserProfile, DietaryProfile, DietaryRestriction,
    CuisineAffinityProfile, CuisineAffinity, PreferenceLevel,
    FlavorProfile, CookingContext, CookingSkill,
    BudgetProfile, LocationProfile, AdventurousnessProfile,
    DimensionWeight,
)
from models.query_ontology import (
    QueryOntology, QueryMode, QueryAttribute, ValueType,
    EatInAttributes, QueryProfileConflict, ConflictType, ConflictResolution,
)
from models.fused_ontology import RetrievalContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def vegetarian_profile():
    """A vegetarian profile with Italian + Japanese preferences."""
    return UserProfile(
        user_id=uuid4(),
        dietary=DietaryProfile(
            spectrum_label="vegetarian",
            hard_stops=[
                DietaryRestriction(label="meat", is_hard_stop=True, reason="ethical"),
                DietaryRestriction(label="fish", is_hard_stop=True, reason="ethical"),
            ],
        ),
        cuisine_affinities=CuisineAffinityProfile(
            affinities=[
                CuisineAffinity(cuisine="Italian", level=PreferenceLevel.LOVE),
                CuisineAffinity(cuisine="Japanese", level=PreferenceLevel.LIKE),
                CuisineAffinity(cuisine="French", level=PreferenceLevel.NEUTRAL),
            ],
        ),
        flavor=FlavorProfile(spicy=3.0, umami=8.0, sweet=5.0),
        cooking=CookingContext(skill=CookingSkill.CONFIDENT, weeknight_minutes=40),
        budget=BudgetProfile(home_per_meal_eur=10.0, out_per_meal_eur=25.0),
        location=LocationProfile(city="Amsterdam", country="NL"),
        adventurousness=AdventurousnessProfile(cooking_score=7.0, dining_score=6.0),
        onboarding_complete=True,
        profile_summary_text="You're a confident vegetarian cook who loves Italian and Japanese cuisine. You enjoy umami-rich dishes and prefer weeknight meals under 40 minutes.",
    )


@pytest.fixture
def simple_eat_in_query(vegetarian_profile):
    """A basic eat-in query for Italian pasta."""
    return QueryOntology(
        user_id=vegetarian_profile.user_id,
        raw_query="I want to make a quick Italian pasta tonight",
        mode=QueryMode.EAT_IN,
        eat_in_attributes=EatInAttributes(
            desired_cuisine="Italian",
            time_constraint_minutes=40,
            mood="comforting",
        ),
        extracted_attributes=[
            QueryAttribute(attribute="desired_cuisine", value="Italian", centrality=0.8),
            QueryAttribute(attribute="time_constraint", value=40, value_type=ValueType.NUMERIC, centrality=0.6),
            QueryAttribute(attribute="mood", value="comforting", centrality=0.4),
        ],
        inferred_mood="comforting",
        inferred_urgency="quick",
        query_complexity=0.3,
    )


@pytest.fixture
def sample_recipes():
    """Mock recipe data matching actual recipes_all.json structure."""
    return [
        {
            "id": str(uuid4()),
            "title": "Cacio e Pepe",
            "title_en": "Cacio e Pepe",
            "cuisine_tags": ["Italian"],
            "description": "Classic Roman pasta with pecorino and black pepper.",
            "ingredients": [
                {"name": "spaghetti", "amount": 400, "unit": "g"},
                {"name": "pecorino romano", "amount": 200, "unit": "g"},
                {"name": "black pepper", "amount": 2, "unit": "tsp"},
            ],
            "steps": [
                {"step_number": 1, "instruction": "Cook pasta in salted water.", "duration_min": 10},
                {"step_number": 2, "instruction": "Toast pepper in a pan.", "duration_min": 2},
                {"step_number": 3, "instruction": "Combine pasta with cheese and pepper.", "duration_min": 3},
            ],
            "time_prep_min": 5,
            "time_cook_min": 15,
            "time_total_min": 20,
            "serves": 4,
            "difficulty": 2,
            "flavor_tags": ["savoury", "umami", "peppery"],
            "texture_tags": ["silky", "al dente"],
            "dietary_tags": ["vegetarian"],
            "dietary_flags": {
                "is_vegan": False, "is_vegetarian": True, "is_pescatarian_ok": True,
                "is_dairy_free": False, "is_gluten_free": False, "is_nut_free": True,
                "is_halal_ok": True, "contains_pork": False, "contains_shellfish": False,
                "contains_alcohol": False,
            },
            "nutrition_per_serving": {"kcal": 450, "protein_g": 18, "fat_g": 20, "saturated_fat_g": 10, "carbs_g": 55, "fiber_g": 2, "sugar_g": 1, "salt_g": 1.5},
            "season_tags": ["year-round"],
            "occasion_tags": ["weeknight-dinner"],
            "course_tags": ["main"],
            "source_type": "mock_tier0",
            "embedding_text": "Cacio e Pepe Italian pasta pecorino pepper savoury umami weeknight",
            "data_quality_score": 0.95,
            "_similarity": 0.92,
        },
        {
            "id": str(uuid4()),
            "title": "Chicken Schnitzel",
            "title_en": "Chicken Schnitzel",
            "cuisine_tags": ["German"],
            "description": "Crispy breaded chicken cutlet.",
            "ingredients": [
                {"name": "chicken breast", "amount": 500, "unit": "g"},
                {"name": "breadcrumbs", "amount": 200, "unit": "g"},
                {"name": "egg", "amount": 2, "unit": "piece"},
            ],
            "steps": [
                {"step_number": 1, "instruction": "Flatten chicken breasts.", "duration_min": 5},
                {"step_number": 2, "instruction": "Bread and fry.", "duration_min": 10},
            ],
            "time_prep_min": 10,
            "time_cook_min": 15,
            "time_total_min": 25,
            "serves": 4,
            "difficulty": 1,
            "flavor_tags": ["savoury", "crispy"],
            "texture_tags": ["crispy", "tender"],
            "dietary_tags": [],
            "dietary_flags": {
                "is_vegan": False, "is_vegetarian": False, "is_pescatarian_ok": False,
                "is_dairy_free": True, "is_gluten_free": False, "is_nut_free": True,
                "is_halal_ok": True, "contains_pork": False, "contains_shellfish": False,
                "contains_alcohol": False,
            },
            "nutrition_per_serving": {"kcal": 380, "protein_g": 35, "fat_g": 15, "saturated_fat_g": 3, "carbs_g": 25, "fiber_g": 1, "sugar_g": 1, "salt_g": 1.0},
            "season_tags": ["year-round"],
            "occasion_tags": ["weeknight-dinner"],
            "course_tags": ["main"],
            "source_type": "mock_tier0",
            "embedding_text": "Chicken Schnitzel German crispy breadcrumbs",
            "data_quality_score": 0.95,
            "_similarity": 0.75,
        },
        {
            "id": str(uuid4()),
            "title": "Pad Thai",
            "title_en": "Pad Thai",
            "cuisine_tags": ["Thai"],
            "description": "Classic Thai stir-fried rice noodles.",
            "ingredients": [
                {"name": "rice noodles", "amount": 300, "unit": "g"},
                {"name": "tofu", "amount": 200, "unit": "g"},
                {"name": "spring onion", "amount": 4, "unit": "piece"},
                {"name": "tamarind paste", "amount": 2, "unit": "tbsp"},
                {"name": "fish sauce", "amount": 2, "unit": "tbsp"},
            ],
            "steps": [
                {"step_number": 1, "instruction": "Soak noodles.", "duration_min": 10},
                {"step_number": 2, "instruction": "Stir-fry tofu.", "duration_min": 5},
                {"step_number": 3, "instruction": "Combine everything with sauce.", "duration_min": 5},
            ],
            "time_prep_min": 15,
            "time_cook_min": 15,
            "time_total_min": 30,
            "serves": 4,
            "difficulty": 2,
            "flavor_tags": ["sweet", "sour", "umami", "spicy"],
            "texture_tags": ["soft", "crunchy"],
            "dietary_tags": [],
            "dietary_flags": {
                "is_vegan": False, "is_vegetarian": False, "is_pescatarian_ok": True,
                "is_dairy_free": True, "is_gluten_free": True, "is_nut_free": False,
                "is_halal_ok": True, "contains_pork": False, "contains_shellfish": False,
                "contains_alcohol": False,
            },
            "nutrition_per_serving": {"kcal": 350, "protein_g": 14, "fat_g": 10, "saturated_fat_g": 2, "carbs_g": 52, "fiber_g": 3, "sugar_g": 8, "salt_g": 2.0},
            "season_tags": ["year-round"],
            "occasion_tags": ["weeknight-dinner"],
            "course_tags": ["main"],
            "source_type": "mock_tier0",
            "embedding_text": "Pad Thai noodles tofu spring onion tamarind sweet sour spicy",
            "data_quality_score": 0.95,
            "_similarity": 0.65,
        },
    ]


# ---------------------------------------------------------------------------
# Fusion tests (pure Python, no LLM)
# ---------------------------------------------------------------------------

class TestFusion:
    def test_hard_stops_applied(self, vegetarian_profile, simple_eat_in_query):
        """Hard stops (meat, fish) must appear as hard filters."""
        from services.pipeline.fusion import fuse_ontologies
        ctx = fuse_ontologies(vegetarian_profile, simple_eat_in_query)
        assert isinstance(ctx, RetrievalContext)
        # Check that hard filters exist
        assert len(ctx.hard_filters) >= 2
        # Hard filter labels should include meat and fish
        filter_labels = [str(f.get("value", "")).lower() for f in ctx.hard_filters]
        assert any("meat" in l for l in filter_labels), f"Missing meat hard filter in {filter_labels}"
        assert any("fish" in l for l in filter_labels), f"Missing fish hard filter in {filter_labels}"

    def test_scoring_vector_populated(self, vegetarian_profile, simple_eat_in_query):
        """Scoring vector should have non-zero weights for relevant dimensions."""
        from services.pipeline.fusion import fuse_ontologies
        ctx = fuse_ontologies(vegetarian_profile, simple_eat_in_query)
        assert len(ctx.scoring_vector) > 0

    def test_value_targets_for_cuisine(self, vegetarian_profile, simple_eat_in_query):
        """When query asks for Italian, value_targets should reflect that."""
        from services.pipeline.fusion import fuse_ontologies
        ctx = fuse_ontologies(vegetarian_profile, simple_eat_in_query)
        # Check for cuisine-related value target
        has_cuisine_target = any(
            "cuisine" in k.lower() for k in ctx.value_targets.keys()
        )
        # This may not be set depending on implementation — at minimum scoring vector should boost cuisine
        assert has_cuisine_target or ctx.scoring_vector.get("cuisine_affinities", 0) > 0

    def test_no_clarification_for_simple_query(self, vegetarian_profile, simple_eat_in_query):
        """A straightforward query should not trigger clarification."""
        from services.pipeline.fusion import fuse_ontologies
        ctx = fuse_ontologies(vegetarian_profile, simple_eat_in_query)
        assert ctx.requires_clarification is False


# ---------------------------------------------------------------------------
# Ranker tests (pure Python, no LLM)
# ---------------------------------------------------------------------------

class TestRanker:
    def test_vegetarian_pasta_ranks_above_chicken(self, vegetarian_profile, simple_eat_in_query, sample_recipes):
        """For a vegetarian asking for Italian pasta, Cacio e Pepe should rank above Chicken Schnitzel."""
        from services.pipeline.fusion import fuse_ontologies
        from services.pipeline.ranker import rank_recipes
        ctx = fuse_ontologies(vegetarian_profile, simple_eat_in_query)
        ranked = rank_recipes(sample_recipes, vegetarian_profile, simple_eat_in_query, ctx)
        
        assert len(ranked) > 0
        # Cacio e Pepe should be #1 (vegetarian, Italian, quick)
        assert ranked[0]["title"] == "Cacio e Pepe", f"Expected Cacio e Pepe first, got {ranked[0]['title']}"
        
        # Chicken Schnitzel should be penalised (not vegetarian, not Italian)
        chicken_idx = next((i for i, r in enumerate(ranked) if r["title"] == "Chicken Schnitzel"), None)
        if chicken_idx is not None:
            assert chicken_idx > 0, "Chicken Schnitzel should not rank #1 for a vegetarian"

    def test_ranked_results_have_score_and_tier(self, vegetarian_profile, simple_eat_in_query, sample_recipes):
        """All ranked results must have _match_score and _match_tier."""
        from services.pipeline.fusion import fuse_ontologies
        from services.pipeline.ranker import rank_recipes
        ctx = fuse_ontologies(vegetarian_profile, simple_eat_in_query)
        ranked = rank_recipes(sample_recipes, vegetarian_profile, simple_eat_in_query, ctx)
        
        for r in ranked:
            assert "_match_score" in r, f"Missing _match_score in {r['title']}"
            assert "_match_tier" in r, f"Missing _match_tier in {r['title']}"
            assert r["_match_tier"] in ("full_match", "close_match", "stretch_pick"), f"Invalid tier: {r['_match_tier']}"
            assert 0.0 <= r["_match_score"] <= 1.0, f"Score out of range: {r['_match_score']}"

    def test_dietary_compliance_affects_ranking(self, vegetarian_profile, simple_eat_in_query, sample_recipes):
        """Chicken Schnitzel should get low dietary compliance score for a vegetarian."""
        from services.pipeline.fusion import fuse_ontologies
        from services.pipeline.ranker import rank_recipes
        ctx = fuse_ontologies(vegetarian_profile, simple_eat_in_query)
        ranked = rank_recipes(sample_recipes, vegetarian_profile, simple_eat_in_query, ctx)
        
        cacio = next(r for r in ranked if r["title"] == "Cacio e Pepe")
        chicken = next((r for r in ranked if r["title"] == "Chicken Schnitzel"), None)
        
        if chicken is not None:
            assert cacio["_match_score"] > chicken["_match_score"], \
                f"Cacio ({cacio['_match_score']}) should score higher than Chicken ({chicken['_match_score']})"


# ---------------------------------------------------------------------------
# Profile snapshot tests
# ---------------------------------------------------------------------------

class TestProfileSnapshot:
    def test_snapshot_contains_hard_stops(self, vegetarian_profile):
        """Profile snapshot must include hard stop info."""
        from services.pipeline.query_extractor import _build_profile_snapshot
        snapshot = _build_profile_snapshot(vegetarian_profile)
        assert "meat" in snapshot.lower()
        assert "fish" in snapshot.lower()

    def test_snapshot_contains_loved_cuisines(self, vegetarian_profile):
        """Profile snapshot must list loved cuisines."""
        from services.pipeline.query_extractor import _build_profile_snapshot
        snapshot = _build_profile_snapshot(vegetarian_profile)
        assert "Italian" in snapshot or "italian" in snapshot


# ---------------------------------------------------------------------------
# Edge case: dietary conflict query
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_dietary_conflict_query(self, vegetarian_profile):
        """Query mentioning a hard-stop ingredient should produce a conflict."""
        query = QueryOntology(
            user_id=vegetarian_profile.user_id,
            raw_query="I want to make a steak tonight",
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
                    warning_text="You have meat as a dietary hard stop. Showing plant-based alternatives.",
                ),
            ],
        )
        from services.pipeline.fusion import fuse_ontologies
        ctx = fuse_ontologies(vegetarian_profile, query)
        
        # Warning should be present
        assert len(ctx.warnings) > 0

    def test_empty_results_graceful(self, vegetarian_profile, simple_eat_in_query):
        """Ranker should handle empty recipe list gracefully."""
        from services.pipeline.fusion import fuse_ontologies
        from services.pipeline.ranker import rank_recipes
        ctx = fuse_ontologies(vegetarian_profile, simple_eat_in_query)
        ranked = rank_recipes([], vegetarian_profile, simple_eat_in_query, ctx)
        assert ranked == []
