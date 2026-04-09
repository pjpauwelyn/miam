"""
Shared test fixtures for miam backend tests.
"""
import json
import os
import sys
from pathlib import Path

import pytest

# Ensure backend modules are importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Set required env vars for tests if not already set
os.environ.setdefault("MISTRAL_API_KEY", "test-key-for-unit-tests")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("TIER2_APPROVED", "false")


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def sample_recipe():
    """A valid sample recipe matching the RecipeDocument schema."""
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "title": "Pappa al Pomodoro",
        "title_en": "Tuscan Tomato Bread Soup",
        "cuisine_tags": ["Italian"],
        "region_tag": "Tuscany",
        "description": "A rustic Tuscan soup made with stale bread and ripe tomatoes.",
        "ingredients": [
            {"name": "stale bread", "amount": 300, "unit": "g", "notes": "day-old ciabatta", "is_optional": False, "substitutions": [{"substitute": "focaccia", "ratio": "1:1", "notes": "Any stale Italian bread works"}]},
            {"name": "tinned tomatoes", "amount": 400, "unit": "g", "notes": None, "is_optional": False, "substitutions": []},
            {"name": "garlic", "amount": 3, "unit": "clove", "notes": None, "is_optional": False, "substitutions": []},
            {"name": "basil", "amount": 1, "unit": "bunch", "notes": "fresh", "is_optional": False, "substitutions": []},
            {"name": "olive oil", "amount": 60, "unit": "ml", "notes": "extra virgin", "is_optional": False, "substitutions": []},
        ],
        "steps": [
            {"step_number": 1, "instruction": "Tear the bread into rough pieces.", "duration_min": 3, "technique_tags": ["tear"]},
            {"step_number": 2, "instruction": "Sauté garlic in olive oil until golden.", "duration_min": 3, "technique_tags": ["sauté"]},
            {"step_number": 3, "instruction": "Add tomatoes and simmer for 15 minutes.", "duration_min": 15, "technique_tags": ["simmer"]},
            {"step_number": 4, "instruction": "Stir in bread, season, and let rest 10 minutes.", "duration_min": 10, "technique_tags": ["stir"]},
        ],
        "time_prep_min": 10,
        "time_cook_min": 25,
        "time_total_min": 35,
        "serves": 4,
        "difficulty": 1,
        "flavor_tags": ["savoury", "herby", "acidic"],
        "texture_tags": ["soft", "rustic"],
        "dietary_tags": ["vegan"],
        "dietary_flags": {
            "is_vegan": True, "is_vegetarian": True, "is_pescatarian_ok": True,
            "is_dairy_free": True, "is_gluten_free": False, "is_nut_free": True,
            "is_halal_ok": True, "contains_pork": False, "contains_shellfish": False,
            "contains_alcohol": False, "vegan_if_substituted": False, "gluten_free_if_substituted": False,
        },
        "nutrition_per_serving": {
            "kcal": 280, "protein_g": 8, "fat_g": 14, "saturated_fat_g": 2,
            "carbs_g": 32, "fiber_g": 4, "sugar_g": 6, "salt_g": 1.0,
        },
        "season_tags": ["summer"],
        "occasion_tags": ["weeknight-dinner"],
        "course_tags": ["main", "soup"],
        "image_placeholder": "",
        "source_type": "mock_tier0",
        "wine_pairing_notes": "A light Chianti complements the earthy flavours.",
        "tips": ["Use day-old bread for better texture"],
        "embedding_text": "Pappa al Pomodoro Tuscan Tomato Bread Soup Italian savoury herby stale bread tomatoes garlic basil",
        "created_at": "2026-04-07T00:00:00Z",
        "data_quality_score": 0.95,
    }


@pytest.fixture
def sample_restaurant():
    """A valid sample restaurant in FSQ response format."""
    return {
        "id": "00000000-0000-0000-0000-000000000002",
        "fsq_place_id": "4a1234567890abcdef123456",
        "name": "De Kas",
        "address": "Kamerlingh Onneslaan 3, 1097 DE Amsterdam",
        "neighborhood": "Oost",
        "city": "Amsterdam",
        "country": "NL",
        "cuisine_tags": {"primary": "Dutch", "secondary": ["French", "Farm-to-table"]},
        "vibe_tags": ["romantic", "upscale", "garden-dining"],
        "price_range": "€€€€",
        "coordinates": {"lat": 52.3555, "lng": 4.9208},
        "phone": "+31201234567",
        "website_url": "https://www.restaurantdekas.com",
        "opening_hours": {
            "monday": "12:00-14:00, 18:30-22:00",
            "tuesday": "12:00-14:00, 18:30-22:00",
            "wednesday": "12:00-14:00, 18:30-22:00",
            "thursday": "12:00-14:00, 18:30-22:00",
            "friday": "12:00-14:00, 18:30-22:00",
            "saturday": "18:30-22:00",
            "sunday": None,
        },
        "menu_summary": "Seasonal tasting menus using greenhouse-grown ingredients.",
        "menu_items": [{"name": "Seasonal Tasting Menu", "description": "5-course menu", "price_eur": 72.50, "course": "tasting", "dietary_tags": ["vegetarian-option"]}],
        "review_summary": "Exceptional greenhouse dining experience.",
        "review_count_estimate": 1200,
        "rating_estimate": 4.6,
        "specialties": ["seasonal tasting menu", "greenhouse vegetables"],
        "dietary_options": {"vegan_ok": True, "vegetarian_ok": True, "halal_ok": False, "gluten_free_ok": True, "kosher_ok": False},
        "reservation_url": "https://www.restaurantdekas.com/reserveren",
        "is_open": True,
        "closed_reason": None,
        "last_verified_date": "2026-03-15",
        "data_quality_score": 0.95,
        "embedding_text": "De Kas Dutch French farm-to-table Oost romantic upscale garden seasonal greenhouse",
        "created_at": "2026-04-07T00:00:00Z",
    }


@pytest.fixture
def recipes_path():
    """Path to all mock recipes."""
    return PROJECT_ROOT / "data" / "recipes" / "recipes_all.json"


@pytest.fixture
def restaurants_path():
    """Path to all mock restaurants."""
    return PROJECT_ROOT / "data" / "restaurants" / "restaurants_all.json"
