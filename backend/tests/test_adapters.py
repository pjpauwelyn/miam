"""
Adapter unit tests — each adapter on sample data.
"""
import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch

from services.adapters.base import TierNotApprovedError
from services.adapters.the_meal_db import TheMealDBAdapter
from services.adapters.edamam import EdamamAdapter
from services.adapters.fsq_live import FSQLiveAdapter
from services.adapters.fsq_os import FSQOSAdapter
from services.adapters.osm import OSMAdapter
from services.adapters.open_food_facts import OpenFoodFactsAdapter
from services.adapters.recipe_nlg import RecipeNLGAdapter
from services.synonym_resolver import to_eu, to_us, normalize_ingredient, get_all_variants


class TestTheMealDBAdapter:
    def test_adapt_flat_ingredients(self):
        adapter = TheMealDBAdapter()
        raw = {
            "strMeal": "Chicken Curry",
            "strArea": "Indian",
            "strCategory": "Main",
            "strInstructions": "Cook the chicken.\r\nAdd curry sauce.\r\nServe with rice.",
            "strIngredient1": "Chicken",
            "strIngredient2": "Curry Paste",
            "strIngredient3": "Coconut Milk",
            "strIngredient4": "",
            "strMeasure1": "500g",
            "strMeasure2": "2 tbsp",
            "strMeasure3": "400ml",
            "strMeasure4": "",
        }
        recipe = adapter.adapt(raw)
        assert recipe.title == "Chicken Curry"
        assert len(recipe.ingredients) == 3
        assert recipe.ingredients[0].name == "Chicken"
        assert len(recipe.steps) == 3
        assert recipe.source_type == "themealdb"


class TestEdamamAdapter:
    def test_tier2_not_approved_raises(self):
        """EdamamAdapter.adapt({}) must raise TierNotApprovedError when TIER2_APPROVED is not set."""
        with patch.dict(os.environ, {"TIER2_APPROVED": "false"}):
            adapter = EdamamAdapter()
            with pytest.raises(TierNotApprovedError):
                adapter.adapt({})

    def test_tier2_not_set_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TIER2_APPROVED", None)
            adapter = EdamamAdapter()
            with pytest.raises(TierNotApprovedError):
                adapter.adapt({})


class TestFSQLiveAdapter:
    def test_tier2_not_approved_raises(self):
        with patch.dict(os.environ, {"TIER2_APPROVED": "false"}):
            adapter = FSQLiveAdapter()
            with pytest.raises(TierNotApprovedError):
                adapter.search(52.37, 4.90)


class TestFSQOSAdapter:
    @pytest.fixture
    def adapter_with_data(self, tmp_path):
        """Create a temporary FSQ envelope file and load it."""
        data = {
            "results": [
                {
                    "id": "00000000-0000-0000-0000-000000000001",
                    "name": "Test Restaurant",
                    "address": "Teststraat 1",
                    "neighborhood": "Centrum",
                    "city": "Amsterdam",
                    "country": "NL",
                    "cuisine_tags": {"primary": "Dutch", "secondary": []},
                    "vibe_tags": ["casual"],
                    "price_range": "€€",
                    "coordinates": {"lat": 52.3676, "lng": 4.9041},
                    "opening_hours": {},
                    "dietary_options": {"vegan_ok": True, "vegetarian_ok": True},
                    "is_open": True,
                    "data_quality_score": 0.8,
                    "embedding_text": "Test Dutch casual Centrum",
                    "created_at": "2026-04-07T00:00:00Z",
                },
                {
                    "id": "00000000-0000-0000-0000-000000000002",
                    "name": "Far Away Restaurant",
                    "address": "Verre Weg 99",
                    "neighborhood": "Amstelveen",
                    "city": "Amsterdam",
                    "country": "NL",
                    "cuisine_tags": {"primary": "French", "secondary": []},
                    "vibe_tags": ["upscale"],
                    "price_range": "€€€€",
                    "coordinates": {"lat": 52.30, "lng": 4.85},  # Far from centre
                    "opening_hours": {},
                    "dietary_options": {},
                    "is_open": True,
                    "data_quality_score": 0.7,
                    "embedding_text": "French upscale Amstelveen",
                    "created_at": "2026-04-07T00:00:00Z",
                },
            ],
            "context": {
                "geo_bounds": {
                    "circle": {
                        "center": {"latitude": 52.3676, "longitude": 4.9041},
                        "radius": 10000,
                    }
                }
            },
        }
        json_path = tmp_path / "test_restaurants.json"
        json_path.write_text(json.dumps(data))
        return FSQOSAdapter(data_path=str(json_path))

    def test_search_returns_fsq_shape(self, adapter_with_data):
        result = adapter_with_data.search(lat=52.3676, lng=4.9041, radius_m=2000)
        assert "results" in result
        assert "context" in result
        assert len(result["results"]) <= 20

    def test_search_filters_by_radius(self, adapter_with_data):
        # Small radius should exclude the far restaurant
        result = adapter_with_data.search(lat=52.3676, lng=4.9041, radius_m=500)
        names = [r["name"] for r in result["results"]]
        assert "Far Away Restaurant" not in names

    def test_search_respects_limit(self, adapter_with_data):
        result = adapter_with_data.search(lat=52.3676, lng=4.9041, radius_m=20000, limit=1)
        assert len(result["results"]) <= 1

    def test_adapt_to_restaurant_document(self, adapter_with_data):
        raw = adapter_with_data._restaurants[0]
        doc = adapter_with_data.adapt(raw)
        assert doc.name == "Test Restaurant"
        assert doc.cuisine_tags.primary == "Dutch"


class TestOSMAdapter:
    def test_parse_opening_hours(self):
        adapter = OSMAdapter()
        raw = {
            "tags": {
                "opening_hours": "Mo-Fr 12:00-22:00; Sa-Su 11:00-23:00",
                "cuisine": "italian;pizza",
                "diet:vegan": "yes",
                "outdoor_seating": "yes",
                "name": "Test Ristorante",
            },
            "lat": 52.37,
            "lon": 4.90,
        }
        enrichment = adapter.adapt(raw)
        assert "opening_hours" in enrichment
        assert enrichment["cuisine_primary"] == "Italian"
        assert enrichment["cuisine_secondary"] == ["Pizza"]
        assert enrichment["dietary_options"].vegan_ok is True
        assert "outdoor-seating" in enrichment["vibe_tag_additions"]


class TestOpenFoodFactsAdapter:
    def test_extract_nutrition(self):
        adapter = OpenFoodFactsAdapter()
        raw = {
            "product_name": "Olive Oil",
            "nutriments": {
                "energy-kcal_100g": 884,
                "proteins_100g": 0,
                "fat_100g": 100,
                "saturated-fat_100g": 14,
                "carbohydrates_100g": 0,
                "fiber_100g": 0,
                "sugars_100g": 0,
                "salt_100g": 0,
            },
        }
        result = adapter.adapt(raw)
        assert result["nutrition_per_100g"].kcal == 884
        assert result["nutrition_per_100g"].fat_g == 100.0


class TestRecipeNLGAdapter:
    def test_adapt_recipenlg_format(self):
        adapter = RecipeNLGAdapter()
        raw = {
            "title": "Simple Pasta",
            "ingredients": ["200g pasta", "2 cloves garlic", "100ml olive oil"],
            "directions": ["Boil pasta.", "Sauté garlic in oil.", "Toss together."],
            "NER": ["pasta", "garlic", "olive oil"],
        }
        recipe = adapter.adapt(raw)
        assert recipe.title == "Simple Pasta"
        assert len(recipe.ingredients) == 3
        assert len(recipe.steps) == 3
        assert recipe.source_type == "recipenlg"


class TestSynonymResolver:
    def test_eu_to_us(self):
        assert to_us("aubergine") == "eggplant"
        assert to_us("courgette") == "zucchini"
        assert to_us("coriander") == "cilantro"

    def test_us_to_eu(self):
        assert to_eu("eggplant") == "aubergine"
        assert to_eu("zucchini") == "courgette"
        assert to_eu("cilantro") == "coriander"

    def test_normalize(self):
        assert normalize_ingredient("eggplant") == "aubergine"
        assert normalize_ingredient("aubergine") == "aubergine"

    def test_get_all_variants(self):
        variants = get_all_variants("aubergine")
        assert "aubergine" in variants
        assert "eggplant" in variants

    def test_unknown_ingredient_unchanged(self):
        assert to_eu("quinoa") == "quinoa"
        assert to_us("quinoa") == "quinoa"

    def test_case_insensitive(self):
        assert to_us("Aubergine") == "eggplant"
        assert to_eu("Eggplant") == "aubergine"
