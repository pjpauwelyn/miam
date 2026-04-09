"""
FSQLiveAdapter — Tier 2 paid Foursquare live API adapter (DORMANT).

Makes live calls to the Foursquare Places API for real-time restaurant data.
LOCKED until TIER2_APPROVED=true is set by stakeholder.

Foursquare live API pricing: $0–$150/month depending on call volume.
"""
from __future__ import annotations

import os
from typing import Any

from .base import BaseAdapter, TierNotApprovedError

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from models.restaurant import RestaurantDocument


class FSQLiveAdapter(BaseAdapter):
    """
    Live Foursquare Places API adapter.
    Tier 2 — dormant until TIER2_APPROVED=true.

    In production (Phase 7+), this replaces FSQOSAdapter for real-time
    restaurant data. The upstream pipeline code is identical — only the
    adapter implementation changes.
    """

    def _check_tier_approval(self) -> None:
        """Check that Tier 2 is approved before any operation."""
        if os.getenv("TIER2_APPROVED", "").lower() != "true":
            raise TierNotApprovedError(
                "Foursquare live API is a Tier 2 paid API ($0-$150/month). "
                "Set TIER2_APPROVED=true in .env after stakeholder approval. "
                "Do not configure without written sign-off."
            )

    def search(
        self,
        lat: float,
        lng: float,
        radius_m: int = 2000,
        categories: list[str] | None = None,
        query: str | None = None,
        limit: int = 20,
    ) -> dict:
        """
        Search Foursquare Places API for restaurants near a location.
        Returns FSQ places/search-compatible response dict.
        """
        self._check_tier_approval()

        # Implementation would call the Foursquare API here
        # For now, raise to prevent accidental use
        raise NotImplementedError(
            "FSQLiveAdapter.search() is not yet implemented. "
            "Use FSQOSAdapter for Phase 0-6."
        )

    def adapt(self, raw: dict) -> RestaurantDocument:
        """Normalise a live Foursquare API response to canonical RestaurantDocument."""
        self._check_tier_approval()

        # Implementation would normalise live FSQ response here
        # Same normalisation logic as FSQOSAdapter.adapt() but for live API format
        raise NotImplementedError(
            "FSQLiveAdapter.adapt() is not yet implemented. "
            "Use FSQOSAdapter for Phase 0-6."
        )
