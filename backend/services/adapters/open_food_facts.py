"""
OpenFoodFactsAdapter — Tier 1 adapter for EU product/ingredient data.

Open Food Facts (ODbL license) provides nutrition data for EU products.
Used to enrich recipes with accurate nutritional information.
This adapter normalises OFF nutriments JSONL to ingredient/nutrition overlays.
"""
from __future__ import annotations

from .base import BaseAdapter

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from models.recipe import NutritionPerServing


class OpenFoodFactsAdapter(BaseAdapter):
    """
    Converts Open Food Facts product records to nutrition data.

    OFF nutriments structure:
    {
        "product_name": "...",
        "nutriments": {
            "energy-kcal_100g": 250,
            "proteins_100g": 10.5,
            "fat_100g": 8.2,
            "saturated-fat_100g": 2.1,
            "carbohydrates_100g": 30.0,
            "fiber_100g": 3.5,
            "sugars_100g": 5.0,
            "salt_100g": 0.8
        }
    }
    """

    def adapt(self, raw: dict) -> dict:
        """
        Extract nutrition-per-100g from an OFF product record.
        Returns a dict suitable for enriching a RecipeDocument's nutrition.
        Note: This adapter doesn't return a RecipeDocument directly —
        it provides nutrition overlays.
        """
        nutriments = raw.get("nutriments", {})

        return {
            "product_name": raw.get("product_name", ""),
            "nutrition_per_100g": NutritionPerServing(
                kcal=int(nutriments.get("energy-kcal_100g", 0)),
                protein_g=round(nutriments.get("proteins_100g", 0), 1),
                fat_g=round(nutriments.get("fat_100g", 0), 1),
                saturated_fat_g=round(nutriments.get("saturated-fat_100g", 0), 1),
                carbs_g=round(nutriments.get("carbohydrates_100g", 0), 1),
                fiber_g=round(nutriments.get("fiber_100g", 0), 1),
                sugar_g=round(nutriments.get("sugars_100g", 0), 1),
                salt_g=round(nutriments.get("salt_100g", 0), 2),
            ),
            "allergens": raw.get("allergens_tags", []),
            "labels": raw.get("labels_tags", []),
        }

    @staticmethod
    def _estimate_grams(amount: float, unit: str) -> float:
        """Rough conversion of various units to grams."""
        unit_to_grams = {
            "g": 1.0,
            "kg": 1000.0,
            "ml": 1.0,  # Water-based approximation
            "dl": 100.0,
            "cl": 10.0,
            "l": 1000.0,
            "tbsp": 15.0,
            "tsp": 5.0,
            "piece": 100.0,  # Very rough average
            "bunch": 50.0,
            "pinch": 1.0,
        }
        factor = unit_to_grams.get(unit.lower(), 100.0)
        return amount * factor
