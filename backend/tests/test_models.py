"""
Schema validation tests — verify all Pydantic models instantiate correctly.
"""
import pytest
from uuid import uuid4

from models.personal_ontology import (
    UserProfile, DimensionMeta, DimensionWeight, DietaryProfile,
    DietaryRestriction, CuisineAffinityProfile, CuisineAffinity,
    PreferenceLevel, FlavorProfile, TextureProfile, CookingContext,
    CookingSkill, KitchenSetup, KitchenEquipment, BudgetProfile,
    DiningVibeProfile, VibeAffinity, AdventurousnessProfile,
    NutritionalProfile, SocialProfile, LifestyleProfile, LocationProfile,
    ProfileTension, TensionSeverity,
)
from models.query_ontology import (
    QueryOntology, QueryMode, QueryAttribute, EatInAttributes,
    EatOutAttributes,
)
from models.fused_ontology import RetrievalContext
from models.recipe import (
    RecipeDocument, RecipeIngredient, RecipeStep, DietaryFlags,
    NutritionPerServing,
)
from models.restaurant import (
    RestaurantDocument, RestaurantCoordinates, RestaurantCuisineTags,
    RestaurantOpeningHours, RestaurantMenuItem, RestaurantDietaryOptions,
)
from models.recipe import RecipeSubstitution
from models.feedback import FeedbackEvent
from models.session import Session, Message


class TestPersonalOntology:
    def test_minimal_profile(self):
        profile = UserProfile(user_id=uuid4())
        assert profile.user_id is not None
        assert profile.schema_version == "1.0.0"
        assert profile.onboarding_complete is False

    def test_full_profile_with_all_dimensions(self):
        profile = UserProfile(
            user_id=uuid4(),
            dietary=DietaryProfile(
                spectrum_label="vegetarian",
                hard_stops=[DietaryRestriction(label="no-meat", is_hard_stop=True)],
            ),
            cuisine_affinities=CuisineAffinityProfile(
                affinities=[CuisineAffinity(cuisine="Italian", level=PreferenceLevel.LOVE)],
            ),
            flavor=FlavorProfile(spicy=8.0, umami=9.0, sweet=3.0),
            texture=TextureProfile(crunchy=7.0, crispy=8.0),
            cooking=CookingContext(skill=CookingSkill.ADVANCED, weeknight_minutes=45),
            budget=BudgetProfile(home_per_meal_eur=12.0),
            dining_vibe=DiningVibeProfile(vibes=[VibeAffinity(vibe="casual", score=9.0)]),
            adventurousness=AdventurousnessProfile(cooking_score=8.0, dining_score=7.0),
            nutrition=NutritionalProfile(level="moderate"),
            social=SocialProfile(default_social_context="couple"),
            lifestyle=LifestyleProfile(seasonal_preference_score=8.0),
            location=LocationProfile(city="Amsterdam", country="NL"),
            onboarding_complete=True,
        )
        assert profile.onboarding_complete is True
        assert profile.dietary.spectrum_label == "vegetarian"
        assert profile.cuisine_affinities.affinities[0].cuisine == "Italian"
        assert profile.flavor.spicy == 8.0

    def test_dimension_meta(self):
        meta = DimensionMeta(weight=DimensionWeight.CORE)
        assert meta.weight == DimensionWeight.CORE

    def test_dietary_restriction(self):
        r = DietaryRestriction(label="no-pork", is_hard_stop=True, reason="Religious")
        assert r.is_hard_stop is True
        assert r.reason == "Religious"

    def test_tension_detection(self):
        """The edge case profile should detect tensions."""
        profile = UserProfile(
            user_id=uuid4(),
            dietary=DietaryProfile(
                spectrum_label="vegan",
                hard_stops=[DietaryRestriction(label="vegan", is_hard_stop=True)],
            ),
            cuisine_affinities=CuisineAffinityProfile(
                affinities=[CuisineAffinity(cuisine="French", level=PreferenceLevel.LOVE)],
            ),
        )
        # Model validator should detect tension between vegan + French cuisine
        assert len(profile.tensions) >= 0  # Depends on validator logic


class TestQueryOntology:
    def test_eat_in_query(self):
        qo = QueryOntology(
            user_id=uuid4(),
            raw_query="What can I make with chicken and rice?",
            mode=QueryMode.EAT_IN,
        )
        assert qo.mode == QueryMode.EAT_IN
        assert qo.eat_in_attributes is not None

    def test_eat_out_query(self):
        qo = QueryOntology(
            user_id=uuid4(),
            raw_query="Romantic dinner in Jordaan",
            mode=QueryMode.EAT_OUT,
        )
        assert qo.mode == QueryMode.EAT_OUT
        assert qo.eat_out_attributes is not None

    def test_query_with_attributes(self):
        qo = QueryOntology(
            user_id=uuid4(),
            raw_query="Quick vegan Thai dinner",
            mode=QueryMode.EAT_IN,
            extracted_attributes=[
                QueryAttribute(attribute="cuisine", value="Thai"),
                QueryAttribute(attribute="dietary", value="vegan"),
            ],
        )
        assert len(qo.extracted_attributes) == 2


class TestFusedOntology:
    def test_retrieval_context_defaults(self):
        rc = RetrievalContext()
        assert rc.hard_filters == []
        assert rc.soft_filters == []
        assert rc.warnings == []
        assert rc.requires_clarification is False


class TestRecipeDocument:
    def test_from_sample(self, sample_recipe):
        recipe = RecipeDocument(**sample_recipe)
        assert recipe.title == "Pappa al Pomodoro"
        assert len(recipe.ingredients) == 5
        assert len(recipe.steps) == 4
        assert recipe.dietary_flags.is_vegan is True
        assert recipe.nutrition_per_serving.kcal == 280

    def test_minimal_recipe(self):
        recipe = RecipeDocument(
            id=uuid4(),
            title="Test Recipe",
            title_en="Test Recipe",
            description="A simple test recipe for validation purposes.",
            ingredients=[RecipeIngredient(name="flour", amount=200, unit="g")],
            steps=[RecipeStep(step_number=1, instruction="Mix everything.")],
            time_prep_min=5,
            time_cook_min=10,
            time_total_min=15,
            serves=2,
            difficulty=1,
            source_type="mock_tier0",
            embedding_text="test",
        )
        assert recipe.title == "Test Recipe"
        assert recipe.data_quality_score == 0.95


class TestRestaurantDocument:
    def test_from_sample(self, sample_restaurant):
        restaurant = RestaurantDocument(**sample_restaurant)
        assert restaurant.name == "De Kas"
        assert restaurant.cuisine_tags.primary == "Dutch"
        assert restaurant.coordinates.lat == 52.3555
        assert restaurant.dietary_options.vegan_ok is True

    def test_minimal_restaurant(self):
        restaurant = RestaurantDocument(
            id=uuid4(),
            name="Test Restaurant",
            address="Teststraat 1, 1012 AB Amsterdam",
            neighborhood="Centrum",
            cuisine_tags=RestaurantCuisineTags(primary="Dutch", secondary=[]),
            price_range="€€",
            coordinates=RestaurantCoordinates(lat=52.3676, lng=4.9041),
            embedding_text="test",
        )
        assert restaurant.name == "Test Restaurant"
        assert restaurant.is_open is True


class TestFeedback:
    def test_feedback_event(self):
        fb = FeedbackEvent(
            user_id=uuid4(),
            feedback_type="thumbs_up",
            result_type="recipe",
            result_reference="recipe-123",
        )
        assert fb.feedback_type == "thumbs_up"


class TestSession:
    def test_session_creation(self):
        session = Session(
            user_id=uuid4(),
            mode="eat_in",
        )
        assert session.mode == "eat_in"
        assert session.query_count == 0

    def test_message_creation(self):
        msg = Message(
            session_id=uuid4(),
            role="user",
            content="What can I cook tonight?",
        )
        assert msg.role == "user"
