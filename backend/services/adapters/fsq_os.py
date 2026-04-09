"""
FSQOSAdapter — Foursquare Open Source Places adapter.

Phase 0: Loads the local mock restaurant JSON (FSQ places/search envelope).
Phase 3+: Loads the real FSQ OS bulk Parquet file.

The upstream pipeline code is never modified — only the data file changes.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime

from .base import BaseAdapter

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from models.restaurant import (
    RestaurantDocument,
    RestaurantCoordinates,
    RestaurantCuisineTags,
    RestaurantOpeningHours,
    RestaurantMenuItem,
    RestaurantDietaryOptions,
)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in metres between two WGS84 points."""
    R = 6_371_000  # Earth radius in metres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class FSQOSAdapter(BaseAdapter):
    """
    Loads the local mock restaurant JSON (FSQ places/search envelope) and serves
    search results that exactly mirror the live Foursquare places/search response shape.

    In Phase 3, this adapter is upgraded to load the real FSQ OS bulk Parquet file.
    The upstream pipeline code is never modified — only the data file changes.
    """

    def __init__(self, data_path: str = "data/restaurants/restaurants_all.json"):
        path = Path(data_path)
        if not path.exists():
            # Try relative to project root
            alt_path = Path(__file__).resolve().parents[3] / data_path
            if alt_path.exists():
                path = alt_path
            else:
                self._restaurants = []
                self._context = {}
                return

        with open(path, encoding="utf-8") as f:
            envelope = json.load(f)
        self._restaurants = envelope.get("results", [])
        self._context = envelope.get("context", {})

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
        Return FSQ places/search-compatible response dict.

        Filters by:
        - Haversine distance from (lat, lng)
        - Category label matching (if provided)
        - Keyword matching against name, cuisine, menu_summary (if provided)
        - Only open restaurants (is_open=True) unless explicitly filtered
        """
        results = self._filter(lat, lng, radius_m, categories, query, limit)
        return {"results": results, "context": self._context}

    def adapt(self, raw: dict) -> RestaurantDocument:
        """Normalise a single FSQ OS record to canonical RestaurantDocument."""
        # Extract coordinates from FSQ nested structure or flat structure
        if "geocodes" in raw:
            lat = raw["geocodes"]["main"]["latitude"]
            lng = raw["geocodes"]["main"]["longitude"]
        elif "coordinates" in raw:
            lat = raw["coordinates"]["lat"]
            lng = raw["coordinates"]["lng"]
        else:
            lat, lng = 0.0, 0.0

        # Extract address from FSQ nested structure or flat structure
        if "location" in raw:
            address = raw["location"].get("formatted_address", "")
            city = raw["location"].get("locality", "Amsterdam")
            country = raw["location"].get("country", "NL")
        else:
            address = raw.get("address", "")
            city = raw.get("city", "Amsterdam")
            country = raw.get("country", "NL")

        # Extract cuisine tags
        cuisine_tags = raw.get("cuisine_tags", {})
        if isinstance(cuisine_tags, dict):
            ct = RestaurantCuisineTags(
                primary=cuisine_tags.get("primary", "Unknown"),
                secondary=cuisine_tags.get("secondary", []),
            )
        else:
            ct = RestaurantCuisineTags(primary="Unknown", secondary=[])

        # Extract opening hours
        hours_raw = raw.get("opening_hours", {})
        if isinstance(hours_raw, dict) and any(
            k in hours_raw for k in ("monday", "tuesday", "wednesday")
        ):
            opening_hours = RestaurantOpeningHours(**hours_raw)
        else:
            opening_hours = RestaurantOpeningHours()

        # Extract menu items
        menu_items = []
        for item in raw.get("menu_items", []):
            try:
                menu_items.append(RestaurantMenuItem(**item))
            except Exception:
                pass

        # Extract dietary options
        diet_raw = raw.get("dietary_options", {})
        dietary_options = RestaurantDietaryOptions(**diet_raw) if diet_raw else RestaurantDietaryOptions()

        # Map price integer to symbol (FSQ uses 1-4)
        price_raw = raw.get("price_range", raw.get("price", "€€"))
        if isinstance(price_raw, int):
            price_map = {1: "€", 2: "€€", 3: "€€€", 4: "€€€€"}
            price_range = price_map.get(price_raw, "€€")
        else:
            price_range = str(price_raw) if price_raw else "€€"

        # Build the record ID
        record_id = raw.get("id", str(uuid4()))

        return RestaurantDocument(
            id=record_id,
            fsq_place_id=raw.get("fsq_place_id"),
            name=raw.get("name", "Unknown"),
            address=address,
            neighborhood=raw.get("neighborhood", "Unknown"),
            city=city,
            country=country,
            cuisine_tags=ct,
            vibe_tags=raw.get("vibe_tags", []),
            price_range=price_range,
            coordinates=RestaurantCoordinates(lat=lat, lng=lng),
            phone=raw.get("phone") or raw.get("tel"),
            website_url=raw.get("website_url") or raw.get("website"),
            opening_hours=opening_hours,
            menu_summary=raw.get("menu_summary"),
            menu_items=menu_items,
            review_summary=raw.get("review_summary"),
            review_count_estimate=raw.get("review_count_estimate"),
            rating_estimate=raw.get("rating_estimate"),
            specialties=raw.get("specialties", []),
            dietary_options=dietary_options,
            reservation_url=raw.get("reservation_url"),
            is_open=raw.get("is_open", True),
            closed_reason=raw.get("closed_reason"),
            last_verified_date=raw.get("last_verified_date"),
            data_quality_score=raw.get("data_quality_score", 0.5),
            data_quality_flags=raw.get("data_quality_flags"),
            data_quality_notes=raw.get("data_quality_notes"),
            embedding_text=raw.get("embedding_text", ""),
            created_at=raw.get("created_at", datetime.utcnow().isoformat()),
        )

    def _filter(
        self,
        lat: float,
        lng: float,
        radius_m: int,
        categories: list[str] | None,
        query: str | None,
        limit: int,
    ) -> list:
        """Filter restaurants by distance, category, and keyword."""
        results = []

        for r in self._restaurants:
            # Skip closed restaurants for search results
            if not r.get("is_open", True):
                continue

            # Distance filter
            if "geocodes" in r:
                r_lat = r["geocodes"]["main"]["latitude"]
                r_lng = r["geocodes"]["main"]["longitude"]
            elif "coordinates" in r:
                r_lat = r["coordinates"]["lat"]
                r_lng = r["coordinates"]["lng"]
            else:
                continue

            dist = _haversine_m(lat, lng, r_lat, r_lng)
            if dist > radius_m:
                continue

            # Category filter
            if categories:
                r_cats = []
                if "categories" in r:
                    r_cats = [c.get("name", "").lower() for c in r.get("categories", [])]
                cuisine = r.get("cuisine_tags", {})
                if isinstance(cuisine, dict):
                    r_cats.append(cuisine.get("primary", "").lower())
                    r_cats.extend([s.lower() for s in cuisine.get("secondary", [])])

                if not any(
                    cat.lower() in " ".join(r_cats) for cat in categories
                ):
                    continue

            # Keyword filter
            if query:
                q_lower = query.lower()
                searchable = " ".join([
                    r.get("name", ""),
                    r.get("embedding_text", ""),
                    r.get("menu_summary", "") or "",
                    r.get("neighborhood", ""),
                ]).lower()
                if q_lower not in searchable:
                    continue

            results.append({**r, "_distance_m": dist})

        # Sort by distance
        results.sort(key=lambda x: x.get("_distance_m", 0))

        # Remove internal distance field and limit
        for r in results:
            r.pop("_distance_m", None)

        return results[:limit]
