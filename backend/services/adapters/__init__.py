"""
Data source adapters — one per external data source.

Each adapter converts a source's native format to the canonical
RecipeDocument or RestaurantDocument Pydantic schema.
"""
from .base import BaseAdapter, TierNotApprovedError
from .the_meal_db import TheMealDBAdapter
from .recipe_nlg import RecipeNLGAdapter
from .open_food_facts import OpenFoodFactsAdapter
from .fsq_os import FSQOSAdapter
from .osm import OSMAdapter
from .edamam import EdamamAdapter
from .fsq_live import FSQLiveAdapter

__all__ = [
    "BaseAdapter",
    "TierNotApprovedError",
    "TheMealDBAdapter",
    "RecipeNLGAdapter",
    "OpenFoodFactsAdapter",
    "FSQOSAdapter",
    "OSMAdapter",
    "EdamamAdapter",
    "FSQLiveAdapter",
]
