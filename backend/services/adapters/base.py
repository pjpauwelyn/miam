"""
Base adapter class for all data source adapters.

Each data source has a dedicated adapter whose single responsibility is:
convert the source's native format to the canonical RecipeDocument or
RestaurantDocument Pydantic schema.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Union

import sys
import os

# Ensure backend is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from models.recipe import RecipeDocument
from models.restaurant import RestaurantDocument


class TierNotApprovedError(Exception):
    """Raised when a Tier 2 adapter is called without stakeholder approval."""
    pass


class BaseAdapter(ABC):
    """Abstract base class for all data source adapters."""

    @abstractmethod
    def adapt(self, raw: dict | list) -> Union[RecipeDocument, RestaurantDocument]:
        """
        Convert a single raw record from the source's native format
        to the canonical miam Pydantic schema.
        """
        raise NotImplementedError
