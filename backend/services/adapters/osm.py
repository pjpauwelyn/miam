"""
OSMAdapter — Tier 1 adapter for OpenStreetMap data via Overpass API.

Enriches restaurant records with opening hours, cuisine tags, and
dietary options from OSM tags. Used alongside FSQOSAdapter.
"""
from __future__ import annotations

from .base import BaseAdapter

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from models.restaurant import (
    RestaurantOpeningHours,
    RestaurantDietaryOptions,
)


class OSMAdapter(BaseAdapter):
    """
    Maps OSM (Overpass API) tag key-value pairs to RestaurantDocument enrichment fields.

    OSM tag mapping:
    - opening_hours -> per-day hour strings
    - cuisine -> cuisine_tags
    - diet:vegan/diet:vegetarian/diet:halal -> dietary_options
    - outdoor_seating -> vibe_tags addition
    """

    def adapt(self, raw: dict) -> dict:
        """
        Convert OSM tags to RestaurantDocument enrichment fields.
        Returns a dict of fields to merge into an existing RestaurantDocument,
        not a standalone RestaurantDocument.
        """
        tags = raw.get("tags", {})
        enrichment = {}

        # Parse opening hours
        if "opening_hours" in tags:
            enrichment["opening_hours"] = self._parse_opening_hours(tags["opening_hours"])

        # Parse cuisine tags
        if "cuisine" in tags:
            cuisines = [c.strip() for c in tags["cuisine"].split(";")]
            if cuisines:
                enrichment["cuisine_primary"] = cuisines[0].title()
                enrichment["cuisine_secondary"] = [c.title() for c in cuisines[1:]]

        # Parse dietary options
        dietary = {}
        if tags.get("diet:vegan") in ("yes", "only"):
            dietary["vegan_ok"] = True
        if tags.get("diet:vegetarian") in ("yes", "only"):
            dietary["vegetarian_ok"] = True
        if tags.get("diet:halal") in ("yes", "only"):
            dietary["halal_ok"] = True
        if tags.get("diet:gluten_free") == "yes":
            dietary["gluten_free_ok"] = True
        if tags.get("diet:kosher") in ("yes", "only"):
            dietary["kosher_ok"] = True
        if dietary:
            enrichment["dietary_options"] = RestaurantDietaryOptions(**dietary)

        # Parse vibe-relevant tags
        vibe_additions = []
        if tags.get("outdoor_seating") == "yes":
            vibe_additions.append("outdoor-seating")
        if tags.get("internet_access") in ("yes", "wlan"):
            vibe_additions.append("wifi")
        if tags.get("wheelchair") == "yes":
            vibe_additions.append("wheelchair-accessible")
        if vibe_additions:
            enrichment["vibe_tag_additions"] = vibe_additions

        # Coordinates
        if "lat" in raw and "lon" in raw:
            enrichment["coordinates"] = {
                "lat": float(raw["lat"]),
                "lng": float(raw["lon"]),
            }

        # Name and address
        if "name" in tags:
            enrichment["name"] = tags["name"]
        if "addr:street" in tags:
            house = tags.get("addr:housenumber", "")
            street = tags["addr:street"]
            postcode = tags.get("addr:postcode", "")
            city = tags.get("addr:city", "Amsterdam")
            enrichment["address"] = f"{street} {house}, {postcode} {city}".strip()

        return enrichment

    @staticmethod
    def _parse_opening_hours(oh_string: str) -> RestaurantOpeningHours:
        """
        Parse OSM opening_hours format to per-day strings.
        
        OSM format examples:
        - "Mo-Fr 12:00-22:00; Sa-Su 11:00-23:00"
        - "Mo-Sa 10:00-21:00"
        - "Tu-Su 17:00-23:00; Mo closed"
        """
        day_map = {
            "mo": "monday", "tu": "tuesday", "we": "wednesday",
            "th": "thursday", "fr": "friday", "sa": "saturday",
            "su": "sunday",
        }
        day_order = ["mo", "tu", "we", "th", "fr", "sa", "su"]

        hours = {d: None for d in day_map.values()}

        try:
            parts = oh_string.split(";")
            for part in parts:
                part = part.strip().lower()
                if not part:
                    continue

                # Split into day range and time
                tokens = part.split()
                if len(tokens) < 2:
                    continue

                day_spec = tokens[0]
                time_spec = " ".join(tokens[1:])

                # Parse day range
                if "-" in day_spec:
                    start_day, end_day = day_spec.split("-")
                    start_idx = day_order.index(start_day) if start_day in day_order else 0
                    end_idx = day_order.index(end_day) if end_day in day_order else 6
                    target_days = day_order[start_idx:end_idx + 1]
                elif "," in day_spec:
                    target_days = [d.strip() for d in day_spec.split(",")]
                else:
                    target_days = [day_spec]

                for day_abbr in target_days:
                    full_day = day_map.get(day_abbr)
                    if full_day:
                        hours[full_day] = time_spec if time_spec != "closed" else "closed"

        except (ValueError, IndexError):
            pass  # Return whatever we managed to parse

        return RestaurantOpeningHours(**hours)
