#!/usr/bin/env python3
"""
generate_restaurants.py — Generates 120 Amsterdam restaurant records + 6 edge cases
via the Mistral AI API and saves them in FSQ response-envelope format.

Usage:
    python scripts/generate_restaurants.py

Output:
    data/restaurants/restaurants_all.json
"""

import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
MODEL = "mistral-small-latest"
API_URL = "https://api.mistral.ai/v1/chat/completions"
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "restaurants" / "restaurants_all.json"
PROGRESS_PATH = Path(__file__).parent.parent / "data" / "restaurants" / "_progress.json"
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds
BATCH_SIZE = 5   # restaurants per API call
REQUEST_TIMEOUT = 120  # seconds

HEADERS = {
    "Authorization": f"Bearer {MISTRAL_API_KEY}",
    "Content-Type": "application/json",
}

# ---------------------------------------------------------------------------
# Neighborhood definitions
# ---------------------------------------------------------------------------

NEIGHBORHOODS = [
    {
        "name": "De Pijp",
        "count": 22,
        "lat_range": (52.350, 52.362),
        "lng_range": (4.892, 4.912),
        "description": "Amsterdam's most diverse, bohemian neighbourhood. High restaurant density, Albert Cuyp market area.",
        "streets": "Gerard Doustraat, Ferdinand Bolstraat, Ceintuurbaan, Van Woustraat, Albert Cuypstraat, Sarphatipark, Ruysdaelkade, Stadhouderskade, Lutmastraat, Eerste van der Helststraat",
        "cuisine_batches": [
            ["Indonesian", "Surinamese", "Dutch", "Italian", "Turkish"],
            ["Moroccan", "Vegetarian", "Japanese", "Mediterranean", "French"],
            ["Asian Fusion", "Ethiopian", "Indian", "Seafood", "International"],
            ["Italian", "Turkish", "Dutch", "Surinamese", "Indonesian"],
            ["Vegetarian", "French", "Mediterranean", "Moroccan", "Japanese"],
        ],
        "price_batches": [
            ["€€", "€", "€€", "€€€", "€"],
            ["€€", "€€€", "€€", "€€€€", "€€"],
            ["€", "€€", "€€€", "€€", "€€€€"],
            ["€€", "€", "€€€", "€€", "€"],
            ["€€€", "€€", "€", "€€€", "€€"],
        ],
    },
    {
        "name": "Centrum",
        "count": 20,
        "lat_range": (52.368, 52.380),
        "lng_range": (4.887, 4.907),
        "description": "Amsterdam city centre. Canal ring, Leidseplein, Rembrandtplein. Mix of tourist-facing and local.",
        "streets": "Leidseplein, Rembrandtplein, Utrechtsestraat, Reguliersdwarsstraat, Spui, Spuistraat, Damrak, Nes, Kalverstraat, Herengracht",
        "cuisine_batches": [
            ["Dutch", "French", "Italian", "Japanese", "Mediterranean"],
            ["International", "Dutch", "Indonesian", "Middle Eastern", "Vegetarian"],
            ["French", "Italian", "Japanese", "Seafood", "Asian Fusion"],
            ["Dutch", "International", "Mediterranean", "Middle Eastern", "French"],
        ],
        "price_batches": [
            ["€€", "€€€", "€€", "€€€€", "€"],
            ["€€", "€", "€€€", "€€", "€€€€"],
            ["€€€", "€€", "€", "€€€€", "€€"],
            ["€€", "€€€", "€€", "€", "€€€€"],
        ],
    },
    {
        "name": "Jordaan",
        "count": 15,
        "lat_range": (52.370, 52.382),
        "lng_range": (4.875, 4.893),
        "description": "Upscale artisan neighbourhood. Narrow canals, Indonesian rijsttafel, French bistros, Dutch brown cafes.",
        "streets": "Prinsengracht, Bloemgracht, Westerstraat, Elandsgracht, Noordermarkt, Lindengracht, Tweede Anjeliersdwarsstraat, Jordaan",
        "cuisine_batches": [
            ["Dutch", "Indonesian", "French", "Italian", "Vegetarian"],
            ["French", "Dutch", "Indonesian", "International", "Japanese"],
            ["Italian", "Dutch", "French", "Asian Fusion", "Vegetarian"],
        ],
        "price_batches": [
            ["€€", "€€€", "€€", "€€€€", "€€"],
            ["€€€", "€€", "€€€€", "€€", "€€€"],
            ["€€", "€€€", "€", "€€€", "€€"],
        ],
    },
    {
        "name": "Oud-Zuid",
        "count": 15,
        "lat_range": (52.349, 52.363),
        "lng_range": (4.868, 4.892),
        "description": "Affluent residential area near Vondelpark and Museumplein. Upscale French bistros, modern European.",
        "streets": "P.C. Hooftstraat, Van Baerlestraat, Cornelis Schuytstraat, Roelof Hartstraat, Vondelpark, Museumplein, Jan Luijkenstraat",
        "cuisine_batches": [
            ["French", "Mediterranean", "Dutch", "Italian", "International"],
            ["French", "Dutch", "Italian", "Mediterranean", "Japanese"],
            ["International", "French", "Dutch", "Seafood", "Vegetarian"],
        ],
        "price_batches": [
            ["€€€", "€€", "€€€€", "€€€", "€€"],
            ["€€€€", "€€€", "€€", "€€€", "€€€€"],
            ["€€", "€€€", "€€€€", "€€", "€€€"],
        ],
    },
    {
        "name": "Oost",
        "count": 15,
        "lat_range": (52.354, 52.368),
        "lng_range": (4.920, 4.945),
        "description": "Diverse residential eastern Amsterdam. Surinamese roti shops, Turkish grills, authentic Indonesian, Dappermarkt area.",
        "streets": "Dapperstraat, Eerste van Swindenstraat, Javastraat, Linnaeusstraat, Mauritskade, Pontanusstraat, Vrolikstraat",
        "cuisine_batches": [
            ["Surinamese", "Turkish", "Indonesian", "Middle Eastern", "Ethiopian"],
            ["Turkish", "Surinamese", "Dutch", "Moroccan", "Indian"],
            ["Indonesian", "Turkish", "Surinamese", "Vietnamese", "Middle Eastern"],
        ],
        "price_batches": [
            ["€", "€", "€€", "€€", "€"],
            ["€€", "€", "€€", "€€€", "€"],
            ["€", "€€", "€", "€€€", "€€"],
        ],
    },
    {
        "name": "Nieuw-West",
        "count": 13,
        "lat_range": (52.360, 52.380),
        "lng_range": (4.832, 4.862),
        "description": "Multicultural western Amsterdam. Large Moroccan, Turkish, Afghan communities. Local restaurants.",
        "streets": "Kinkerstraat, Jan van Galenstraat, Bos en Lommerweg, Surinameplein, Slotermeer, Osdorpplein, De Aker",
        "cuisine_batches": [
            ["Moroccan", "Turkish", "Afghan", "Middle Eastern", "Turkish"],
            ["Moroccan", "Turkish", "Middle Eastern", "International", "Afghan"],
            ["Turkish", "Moroccan", "Afghan", "Middle Eastern", "Vegetarian"],
        ],
        "price_batches": [
            ["€", "€", "€€", "€", "€€"],
            ["€", "€€", "€", "€€", "€€€"],
            ["€", "€", "€€", "€€", "€"],
        ],
    },
    {
        "name": "Noord",
        "count": 10,
        "lat_range": (52.385, 52.402),
        "lng_range": (4.883, 4.920),
        "description": "Industrial-chic emerging food scene north of the IJ river. Food halls, creative concepts, modern European.",
        "streets": "NDSM-werf, Buiksloterweg, Overhoeksplein, Johan van Hasseltweg, Distelweg, Watertorenplein",
        "cuisine_batches": [
            ["International", "Asian Fusion", "Vegetarian", "Dutch", "Seafood"],
            ["International", "Dutch", "Japanese", "Vegetarian", "Italian"],
        ],
        "price_batches": [
            ["€€", "€€", "€€€", "€", "€€"],
            ["€€€", "€€", "€", "€€", "€€€€"],
        ],
    },
    {
        "name": "Watergraafsmeer",
        "count": 10,
        "lat_range": (52.345, 52.360),
        "lng_range": (4.920, 4.945),
        "description": "Quiet residential eastern district with Science Park. Neighbourhood restaurants, Dutch, international.",
        "streets": "Middenweg, Kruislaan, Science Park, Linnaeushof, Muiderpoortstation",
        "cuisine_batches": [
            ["Dutch", "Italian", "Japanese", "Seafood", "Indian"],
            ["Dutch", "Italian", "International", "French", "Vegetarian"],
        ],
        "price_batches": [
            ["€€", "€€", "€€€", "€", "€€€"],
            ["€€", "€€€€", "€€", "€", "€€€"],
        ],
    },
]

# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

EDGE_CASES = [
    # EC-1: Permanently closed
    {
        "id": "ec-rest-001",
        "fsq_place_id": None,
        "name": "Restaurant Haesje Claes",
        "address": "Spuistraat 275, 1012 VR Amsterdam",
        "neighborhood": "Centrum",
        "city": "Amsterdam",
        "country": "NL",
        "cuisine_tags": {"primary": "Dutch", "secondary": ["traditional", "tourist-facing"]},
        "vibe_tags": ["traditional", "tourist-trap", "rustic", "lively"],
        "price_range": "€€",
        "coordinates": {"lat": 52.3716, "lng": 4.8912},
        "geocodes": {"main": {"latitude": 52.3716, "longitude": 4.8912}},
        "location": {"formatted_address": "Spuistraat 275, 1012 VR Amsterdam", "locality": "Amsterdam", "country": "NL"},
        "categories": [{"id": 13065, "name": "Restaurant", "short_name": "Restaurant"}],
        "tel": None,
        "phone": None,
        "website": "https://www.haesjeclaes.nl",
        "website_url": "https://www.haesjeclaes.nl",
        "opening_hours": {"monday": "closed", "tuesday": "closed", "wednesday": "closed", "thursday": "closed", "friday": "closed", "saturday": "closed", "sunday": "closed"},
        "hours": {"display": "Permanently closed"},
        "price": 2,
        "menu_summary": "Formerly served traditional Dutch comfort food including stamppot, erwtensoep, and Dutch apple pie. A tourist institution for three decades before closing.",
        "menu_items": [],
        "review_summary": "Haesje Claes was one of Amsterdam's most recognisable Dutch restaurants for over 30 years, occupying a 17th-century canal house near the Spui. Reviewers consistently described it as a reliable choice for visitors wanting traditional Dutch cuisine — stamppot with rookworst, hutspot, and thick erwtensoep — in an authentically Dutch interior. Critics noted that the tourist pricing was steep for the quality, but the atmosphere was genuine. The restaurant closed permanently in January 2026.",
        "review_count_estimate": 4200,
        "rating_estimate": 3.8,
        "specialties": ["Stamppot boerenkool met rookworst", "Erwtensoep", "Hutspot", "Poffertjes", "Dutch apple pie"],
        "dietary_options": {"vegan_ok": False, "vegetarian_ok": True, "halal_ok": False, "gluten_free_ok": False, "kosher_ok": False},
        "reservation_url": None,
        "is_open": False,
        "closed_reason": "Permanently closed since January 2026. Building sold for residential conversion.",
        "last_verified_date": "2026-01-15",
        "data_quality_score": 0.40,
        "data_quality_flags": ["permanently_closed"],
        "data_quality_notes": "Restaurant permanently closed. Retained for pipeline exclusion testing.",
        "embedding_text": "Restaurant Haesje Claes Centrum Dutch traditional tourist-trap rustic stamppot erwtensoep hutspot PERMANENTLY CLOSED",
        "created_at": "2026-04-07T00:00:00Z",
    },
    # EC-2: Temporarily closed for renovation
    {
        "id": "ec-rest-002",
        "fsq_place_id": None,
        "name": "Brasserie Oud Centrum",
        "address": "Kloveniersburgwal 14, 1012 CV Amsterdam",
        "neighborhood": "Centrum",
        "city": "Amsterdam",
        "country": "NL",
        "cuisine_tags": {"primary": "French", "secondary": ["brasserie", "European"]},
        "vibe_tags": ["cozy", "romantic", "fine-dining", "canal-side", "quiet"],
        "price_range": "€€€",
        "coordinates": {"lat": 52.3698, "lng": 4.8985},
        "geocodes": {"main": {"latitude": 52.3698, "longitude": 4.8985}},
        "location": {"formatted_address": "Kloveniersburgwal 14, 1012 CV Amsterdam", "locality": "Amsterdam", "country": "NL"},
        "categories": [{"id": 13065, "name": "Restaurant", "short_name": "Restaurant"}],
        "tel": "+31207654321",
        "phone": "+31207654321",
        "website": "https://www.brasserieoudcentrum.nl",
        "website_url": "https://www.brasserieoudcentrum.nl",
        "opening_hours": {"monday": "closed", "tuesday": "closed", "wednesday": "closed", "thursday": "closed", "friday": "closed", "saturday": "closed", "sunday": "closed"},
        "hours": {"display": "Temporarily closed for renovation — reopening May 2026"},
        "price": 3,
        "menu_summary": "Classic French brasserie fare in an elegant canal-side setting. The kitchen focuses on bistro classics: steak frites, moules marinières, duck confit, and an excellent rotating wine list sourced from small French producers.",
        "menu_items": [
            {"name": "Steak Frites", "description": "200g entrecôte with hand-cut fries and béarnaise sauce.", "price_eur": 28.50, "course": "main", "dietary_tags": ["gluten-free-option"]},
            {"name": "Moules Marinières", "description": "PEI mussels steamed in white wine, shallots, and parsley.", "price_eur": 22.00, "course": "main", "dietary_tags": ["gluten-free"]},
            {"name": "Crème Brûlée", "description": "Vanilla custard with caramelised sugar crust.", "price_eur": 9.50, "course": "dessert", "dietary_tags": ["vegetarian", "gluten-free"]},
        ],
        "review_summary": "Brasserie Oud Centrum occupies a prime spot on the Kloveniersburgwal canal, making it one of Amsterdam's most scenic dining rooms. The French-leaning menu reliably delivers bistro classics executed with care. The wine list tilts toward natural and biodynamic producers from the Loire and Rhône. Currently closed for a full kitchen and interior renovation, expected to reopen in May 2026 with an expanded terrace and updated menu.",
        "review_count_estimate": 850,
        "rating_estimate": 4.3,
        "specialties": ["Steak frites", "Moules marinières", "Duck confit", "Cheese board"],
        "dietary_options": {"vegan_ok": False, "vegetarian_ok": True, "halal_ok": False, "gluten_free_ok": True, "kosher_ok": False},
        "reservation_url": None,
        "is_open": False,
        "closed_reason": "Closed for renovation until May 2026",
        "last_verified_date": "2026-02-01",
        "data_quality_score": 0.45,
        "data_quality_flags": ["temporarily_closed"],
        "data_quality_notes": "Temporarily closed for renovation. Reopen date May 2026.",
        "embedding_text": "Brasserie Oud Centrum Centrum French brasserie cozy romantic fine-dining canal-side steak frites moules marinières TEMPORARILY CLOSED RENOVATION",
        "created_at": "2026-04-07T00:00:00Z",
    },
    # EC-3: Completely missing data (only name + address + coordinates)
    {
        "id": "ec-rest-003",
        "fsq_place_id": None,
        "name": "Snackbar De Hoek",
        "address": "Bilderdijkstraat 101, 1053 KM Amsterdam",
        "neighborhood": "Oud-West",
        "city": "Amsterdam",
        "country": "NL",
        "cuisine_tags": None,
        "vibe_tags": [],
        "price_range": None,
        "coordinates": {"lat": 52.3673, "lng": 4.8701},
        "geocodes": {"main": {"latitude": 52.3673, "longitude": 4.8701}},
        "location": {"formatted_address": "Bilderdijkstraat 101, 1053 KM Amsterdam", "locality": "Amsterdam", "country": "NL"},
        "categories": [],
        "tel": None,
        "phone": None,
        "website": None,
        "website_url": None,
        "opening_hours": {"monday": None, "tuesday": None, "wednesday": None, "thursday": None, "friday": None, "saturday": None, "sunday": None},
        "hours": None,
        "price": None,
        "menu_summary": None,
        "menu_items": [],
        "review_summary": None,
        "review_count_estimate": None,
        "rating_estimate": None,
        "specialties": [],
        "dietary_options": {"vegan_ok": None, "vegetarian_ok": None, "halal_ok": None, "gluten_free_ok": None, "kosher_ok": None},
        "reservation_url": None,
        "is_open": True,
        "closed_reason": None,
        "last_verified_date": None,
        "data_quality_score": 0.05,
        "data_quality_flags": ["missing_cuisine", "missing_price", "missing_menu", "missing_hours", "missing_contact"],
        "data_quality_notes": "Minimal data record — only name, address, and coordinates available. All enrichment fields missing.",
        "embedding_text": "Snackbar De Hoek Oud-West Amsterdam",
        "created_at": "2026-04-07T00:00:00Z",
    },
    # EC-4: Conflicting dietary data (marked halal but menu has pork)
    {
        "id": "ec-rest-004",
        "fsq_place_id": None,
        "name": "Groen & Lekker",
        "address": "Kinkerstraat 88, 1053 EA Amsterdam",
        "neighborhood": "Oud-West",
        "city": "Amsterdam",
        "country": "NL",
        "cuisine_tags": {"primary": "Vegetarian", "secondary": ["healthy", "modern"]},
        "vibe_tags": ["trendy", "instagram-worthy", "casual", "quick-bite", "minimalist"],
        "price_range": "€€",
        "coordinates": {"lat": 52.3657, "lng": 4.8751},
        "geocodes": {"main": {"latitude": 52.3657, "longitude": 4.8751}},
        "location": {"formatted_address": "Kinkerstraat 88, 1053 EA Amsterdam", "locality": "Amsterdam", "country": "NL"},
        "categories": [{"id": 13377, "name": "Vegetarian / Vegan Restaurant", "short_name": "Vegetarian"}],
        "tel": "+31206543210",
        "phone": "+31206543210",
        "website": "https://www.groenenlekker.nl",
        "website_url": "https://www.groenenlekker.nl",
        "opening_hours": {"monday": "10:00-21:00", "tuesday": "10:00-21:00", "wednesday": "10:00-21:00", "thursday": "10:00-21:00", "friday": "10:00-22:00", "saturday": "10:00-22:00", "sunday": "11:00-20:00"},
        "hours": {"display": "Mon-Thu 10:00-21:00; Fri-Sat 10:00-22:00; Sun 11:00-20:00"},
        "price": 2,
        "menu_summary": "Groen & Lekker presents itself as a vegan-friendly, halal-certified healthy eating spot. The menu includes plant-forward bowls, wraps, and smoothies — but also a Bacon & Brie panini and pork rillette board under specials, directly contradicting the stated certifications.",
        "menu_items": [
            {"name": "Buddha Bowl", "description": "Roasted sweet potato, kale, chickpeas, tahini dressing, pomegranate.", "price_eur": 14.50, "course": "main", "dietary_tags": ["vegan", "gluten-free"]},
            {"name": "Groen Burger", "description": "Black bean and beet patty, lettuce, tomato, pickles, house sauce on a brioche bun.", "price_eur": 13.00, "course": "main", "dietary_tags": ["vegetarian"]},
            {"name": "Cashew Caesar Salad", "description": "Romaine, cashew parmesan, house croutons, lemon-anchovy dressing.", "price_eur": 12.50, "course": "main", "dietary_tags": ["vegan"]},
            {"name": "Bacon & Brie Panini", "description": "Smoked bacon, Brie de Meaux, caramelised onion, arugula on sourdough.", "price_eur": 11.00, "course": "main", "dietary_tags": []},
            {"name": "Pork Rillette Board", "description": "House-made pork rillette, cornichons, Dijon mustard, country bread.", "price_eur": 16.50, "course": "sharing", "dietary_tags": []},
            {"name": "Protein Smoothie", "description": "Almond milk, banana, peanut butter, maca, honey.", "price_eur": 7.50, "course": "drink", "dietary_tags": ["vegan"]},
        ],
        "review_summary": "Groen & Lekker presents itself as a vegan-friendly, halal-certified healthy eating spot in Oud-West. The plant-based bowls and smoothies are well-executed. However, several reviewers — particularly those seeking halal or strictly vegan options — have flagged the presence of pork items (a bacon panini and pork rillette) on the menu, directly contradicting the restaurant's stated certifications. This is an active data quality issue that has confused multiple diners with strict dietary requirements.",
        "review_count_estimate": 340,
        "rating_estimate": 3.9,
        "specialties": ["Buddha Bowl", "Groen Burger", "Cashew Caesar Salad"],
        "dietary_options": {"vegan_ok": True, "vegetarian_ok": True, "halal_ok": True, "gluten_free_ok": True, "kosher_ok": False},
        "reservation_url": None,
        "is_open": True,
        "closed_reason": None,
        "last_verified_date": "2026-03-01",
        "data_quality_score": 0.35,
        "data_quality_flags": ["dietary_tag_mismatch", "halal_conflict_pork_items", "vegan_conflict_anchovy_honey"],
        "data_quality_notes": "CONFLICT: halal_ok=true but menu contains bacon and pork rillette. vegan_ok=true but Caesar has anchovy and Smoothie has honey.",
        "embedding_text": "Groen & Lekker Oud-West Vegetarian healthy modern trendy instagram-worthy casual Buddha Bowl Groen Burger DATA QUALITY CONFLICT halal pork vegan anchovy",
        "created_at": "2026-04-07T00:00:00Z",
    },
    # EC-5: Pop-up / food truck
    {
        "id": "ec-rest-005",
        "fsq_place_id": None,
        "name": "Wok on Wheels — Noordermarkt",
        "address": "Noordermarkt (varies by market day), 1015 MV Amsterdam",
        "neighborhood": "Jordaan",
        "city": "Amsterdam",
        "country": "NL",
        "cuisine_tags": {"primary": "Asian Fusion", "secondary": ["Thai", "Vietnamese", "street-food"]},
        "vibe_tags": ["casual", "outdoor-seating", "quick-bite", "local-favorite", "lively", "trendy"],
        "price_range": "€",
        "coordinates": {"lat": 52.3784, "lng": 4.8841},
        "geocodes": {"main": {"latitude": 52.3784, "longitude": 4.8841}},
        "location": {"formatted_address": "Noordermarkt (varies by market day), 1015 MV Amsterdam", "locality": "Amsterdam", "country": "NL"},
        "categories": [{"id": 13338, "name": "Food Truck", "short_name": "Food Truck"}],
        "tel": "+31612345678",
        "phone": "+31612345678",
        "website": "https://www.wokonwheels.nl",
        "website_url": "https://www.wokonwheels.nl",
        "opening_hours": {"monday": "closed", "tuesday": "closed", "wednesday": "closed", "thursday": "10:00-18:00", "friday": "closed", "saturday": "09:00-17:00", "sunday": "closed"},
        "hours": {"display": "Thu 10:00-18:00 (Boerenmarkt); Sat 09:00-17:00 (Noordermarkt). Location varies — check Instagram."},
        "price": 1,
        "menu_summary": "Wok on Wheels is a food truck run by two Dutch-Thai siblings operating exclusively at the Noordermarkt (Saturday) and Boerenmarkt (Thursday). The rotating menu features fresh pad thai, Vietnamese bánh mì, green curry, and seasonal Thai salads prepared to order. Sells out most Saturdays by 14:00.",
        "menu_items": [
            {"name": "Pad Thai", "description": "Rice noodles, tofu or prawn, egg, bean sprouts, roasted peanuts, lime, chilli.", "price_eur": 9.00, "course": "main", "dietary_tags": ["gluten-free", "vegetarian-option"]},
            {"name": "Green Curry Bowl", "description": "Coconut green curry with seasonal vegetables, jasmine rice, fresh basil.", "price_eur": 9.50, "course": "main", "dietary_tags": ["vegan", "gluten-free"]},
            {"name": "Bánh Mì", "description": "Vietnamese baguette with lemongrass chicken, pickled daikon, coriander, sriracha.", "price_eur": 7.50, "course": "main", "dietary_tags": []},
            {"name": "Mango Sticky Rice", "description": "Thai sweet sticky rice with fresh mango and coconut cream.", "price_eur": 5.50, "course": "dessert", "dietary_tags": ["vegan", "gluten-free"]},
        ],
        "review_summary": "Wok on Wheels is a cult favourite at the Noordermarkt. The Saturday queue regularly forms 20 minutes before the truck arrives. The pad thai is widely considered the best in Amsterdam by the market's regulars — light, fragrant, not over-sauced. The bánh mì uses a proper crispy Vietnamese baguette. Service is fast and friendly. A genuinely special experience but requires timing your Saturday right.",
        "review_count_estimate": 520,
        "rating_estimate": 4.7,
        "specialties": ["Pad Thai", "Green Curry Bowl", "Bánh Mì", "Mango Sticky Rice"],
        "dietary_options": {"vegan_ok": True, "vegetarian_ok": True, "halal_ok": False, "gluten_free_ok": True, "kosher_ok": False},
        "reservation_url": None,
        "is_open": True,
        "closed_reason": None,
        "last_verified_date": "2026-03-20",
        "data_quality_score": 0.48,
        "data_quality_flags": ["pop_up_format", "location_variable", "hours_market_dependent"],
        "data_quality_notes": "Food truck — location varies by market day. Only operates Thu and Sat at Noordermarkt/Boerenmarkt. Not a fixed venue.",
        "embedding_text": "Wok on Wheels Noordermarkt Jordaan Asian Fusion Thai Vietnamese street-food casual outdoor quick-bite pad thai bánh mì green curry food truck pop-up market",
        "created_at": "2026-04-07T00:00:00Z",
    },
    # EC-6: Amstelveen (outside Amsterdam proper — tests radius filtering)
    {
        "id": "ec-rest-006",
        "fsq_place_id": None,
        "name": "De Jonge Dikkert",
        "address": "Amsterdamseweg 104a, 1182 HG Amstelveen",
        "neighborhood": "Amstelveen",
        "city": "Amstelveen",
        "country": "NL",
        "cuisine_tags": {"primary": "Dutch", "secondary": ["French", "seasonal", "farm-to-table"]},
        "vibe_tags": ["romantic", "upscale", "garden-dining", "fine-dining", "quiet", "traditional"],
        "price_range": "€€€€",
        "coordinates": {"lat": 52.3072, "lng": 4.8680},
        "geocodes": {"main": {"latitude": 52.3072, "longitude": 4.8680}},
        "location": {"formatted_address": "Amsterdamseweg 104a, 1182 HG Amstelveen", "locality": "Amstelveen", "country": "NL"},
        "categories": [{"id": 13065, "name": "Restaurant", "short_name": "Restaurant"}],
        "tel": "+31206454343",
        "phone": "+31206454343",
        "website": "https://www.dejongedikkert.nl",
        "website_url": "https://www.dejongedikkert.nl",
        "opening_hours": {"monday": "closed", "tuesday": "12:00-14:30, 18:00-22:00", "wednesday": "12:00-14:30, 18:00-22:00", "thursday": "12:00-14:30, 18:00-22:00", "friday": "12:00-14:30, 18:00-22:30", "saturday": "18:00-22:30", "sunday": "12:00-16:00"},
        "hours": {"display": "Tue-Fri 12:00-14:30 & 18:00-22:00; Sat 18:00-22:30; Sun 12:00-16:00"},
        "price": 4,
        "menu_summary": "De Jonge Dikkert is a landmark fine-dining restaurant set in a restored 17th-century windmill on the banks of the Amstel in Amstelveen. The kitchen presents a seasonal Dutch-French menu with produce from local farms. Tasting menus of 4 and 6 courses are the centrepiece.",
        "menu_items": [
            {"name": "4-Course Seasonal Tasting Menu", "description": "Chef's selection using that week's market produce.", "price_eur": 68.00, "course": "tasting", "dietary_tags": ["vegetarian-option"]},
            {"name": "6-Course Grand Menu", "description": "Extended six-course experience with optional wine pairing.", "price_eur": 98.00, "course": "tasting", "dietary_tags": ["vegetarian-option"]},
            {"name": "North Sea Sole Meunière", "description": "Whole Dover sole, brown butter, capers, lemon, potato gratin.", "price_eur": 42.00, "course": "main", "dietary_tags": ["gluten-free"]},
        ],
        "review_summary": "De Jonge Dikkert is consistently rated among the top restaurants in the greater Amsterdam metropolitan area. The windmill setting is unmistakably romantic — a favourite for proposals and anniversaries. The kitchen produces refined Dutch-French cuisine emphasising local seasonality. The service is formal, attentive, and knowledgeable. The main limitation is location: Amstelveen is a 20-minute tram ride from Amsterdam Centraal, placing it outside the standard Amsterdam city radius.",
        "review_count_estimate": 1800,
        "rating_estimate": 4.6,
        "specialties": ["4-Course Seasonal Tasting Menu", "6-Course Grand Menu", "North Sea Sole Meunière"],
        "dietary_options": {"vegan_ok": False, "vegetarian_ok": True, "halal_ok": False, "gluten_free_ok": True, "kosher_ok": False},
        "reservation_url": "https://www.dejongedikkert.nl/reserveren",
        "is_open": True,
        "closed_reason": None,
        "last_verified_date": "2026-03-10",
        "data_quality_score": 0.48,
        "data_quality_flags": ["outside_amsterdam_proper", "radius_filter_test"],
        "data_quality_notes": "Restaurant is in Amstelveen, not Amsterdam. Coordinates (52.3072, 4.8680) fall ~7km outside Amsterdam city centre. Tests radius filtering.",
        "embedding_text": "De Jonge Dikkert Amstelveen Dutch French seasonal farm-to-table romantic upscale fine-dining tasting menu windmill OUTSIDE AMSTERDAM",
        "created_at": "2026-04-07T00:00:00Z",
    },
]

# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a restaurant data specialist for the miam food intelligence app. "
    "Generate realistic Amsterdam restaurant records as a JSON array. "
    "Return ONLY the JSON array — no markdown fences, no explanation, no text before or after the array."
)


def build_prompt(nb: dict, cuisines: list, prices: list, count: int, existing_names: set) -> str:
    avoid = ", ".join(list(existing_names)[:15]) if existing_names else "none"
    lat_min, lat_max = nb["lat_range"]
    lng_min, lng_max = nb["lng_range"]

    return f"""Generate exactly {count} Amsterdam restaurant JSON records for the {nb['name']} neighborhood.

NEIGHBORHOOD: {nb['name']} — {nb['description']}
Streets to use: {nb['streets']}
Coordinate range: lat {lat_min:.4f}–{lat_max:.4f}, lng {lng_min:.4f}–{lng_max:.4f}
Cuisines for this batch (one per restaurant): {', '.join(cuisines[:count])}
Price ranges for this batch: {', '.join(prices[:count])}
Avoid these names (already generated): {avoid}

Each of the {count} records must contain ALL these JSON fields:
{{
  "id": "UUID v4",
  "fsq_place_id": "16-char hex e.g. 4c7e42d07af3f04d",
  "name": "restaurant name",
  "address": "Straatnaam 12, 1072 AB Amsterdam",
  "neighborhood": "{nb['name']}",
  "city": "Amsterdam",
  "country": "NL",
  "cuisine_tags": {{"primary": "...", "secondary": ["...", "..."]}},
  "vibe_tags": ["3-5 from: romantic,casual,family-friendly,date-night,business-lunch,group-dining,solo-friendly,late-night,brunch-spot,terrace,canal-side,trendy,hidden-gem,local-favorite,quick-bite,fine-dining,wine-bar,outdoor-seating,cozy,minimalist,traditional,modern,rustic,lively,quiet"],
  "price_range": "€ or €€ or €€€ or €€€€",
  "coordinates": {{"lat": float, "lng": float}},
  "geocodes": {{"main": {{"latitude": float, "longitude": float}}}},
  "location": {{"formatted_address": "...", "locality": "Amsterdam", "country": "NL"}},
  "categories": [{{"id": 13065, "name": "Restaurant", "short_name": "Restaurant"}}],
  "tel": "+3120XXXXXXX or null",
  "phone": "(same as tel)",
  "website": "https://... or null",
  "website_url": "(same as website)",
  "opening_hours": {{"monday": "HH:MM-HH:MM or closed", "tuesday": "...", "wednesday": "...", "thursday": "...", "friday": "...", "saturday": "...", "sunday": "..."}},
  "hours": {{"display": "brief hours summary"}},
  "price": 1-4,
  "menu_summary": "120-200 word menu description",
  "menu_items": [5-7 items: {{"name":"...","description":"1-2 sentences","price_eur":float,"course":"starter|main|dessert|drink|side|sharing","dietary_tags":[]}}],
  "review_summary": "150-250 word third-person review summary",
  "review_count_estimate": integer,
  "rating_estimate": float 3.5-5.0,
  "specialties": ["3-5 dish names"],
  "dietary_options": {{"vegan_ok":bool,"vegetarian_ok":bool,"halal_ok":bool,"gluten_free_ok":bool,"kosher_ok":bool}},
  "reservation_url": "https://... or null",
  "is_open": true,
  "closed_reason": null,
  "last_verified_date": "2026-03-15",
  "data_quality_score": float 0.75-0.98,
  "data_quality_flags": null,
  "data_quality_notes": null,
  "embedding_text": "name neighborhood cuisine vibe specialties key dishes",
  "created_at": "2026-04-07T00:00:00Z"
}}

Return ONLY a valid JSON array of exactly {count} objects. No markdown. No other text."""


# ---------------------------------------------------------------------------
# API call
# ---------------------------------------------------------------------------


def call_mistral(messages: list, label: str) -> str | None:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"  [{label}] Attempt {attempt}/{MAX_RETRIES}...")
            r = requests.post(
                API_URL,
                headers=HEADERS,
                json={
                    "model": MODEL,
                    "messages": messages,
                    "max_tokens": 7000,
                    "temperature": 0.75,
                },
                timeout=REQUEST_TIMEOUT,
            )
            if r.status_code != 200:
                print(f"  [{label}] HTTP {r.status_code}: {r.text[:200]}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY * attempt)
                    continue
                return None
            return r.json()["choices"][0]["message"]["content"]
        except requests.Timeout:
            print(f"  [{label}] Timeout on attempt {attempt}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
        except Exception as e:
            print(f"  [{label}] Error: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
    return None


# ---------------------------------------------------------------------------
# JSON extraction with partial recovery
# ---------------------------------------------------------------------------


def extract_array(text: str) -> list:
    """Extract JSON array from model output, recovering partial records if needed."""
    if not text:
        return []

    text = text.strip()

    # Strip markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        inner = []
        fence_seen = False
        for line in lines:
            if line.strip().startswith("```"):
                if not fence_seen:
                    fence_seen = True
                    continue
                else:
                    break
            if fence_seen:
                inner.append(line)
        text = "\n".join(inner)

    text = text.strip()

    # Direct parse
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("results", "restaurants", "data", "records"):
                if key in data and isinstance(data[key], list):
                    return data[key]
            return [data]
    except json.JSONDecodeError:
        pass

    # Find array boundaries
    start = text.find("[")
    if start == -1:
        return []
    end = text.rfind("]")
    if end == -1:
        # Attempt to close truncated array
        text = text[start:] + "]"
    else:
        text = text[start : end + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Last resort: extract individual complete objects
    records = []
    depth = 0
    in_string = False
    escape_next = False
    obj_start = None

    for i, ch in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
        if in_string:
            continue
        if ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and obj_start is not None:
                try:
                    obj = json.loads(text[obj_start : i + 1])
                    records.append(obj)
                except json.JSONDecodeError:
                    pass
                obj_start = None

    return records


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------


def generate_embedding_text(r: dict) -> str:
    parts = [r.get("name", ""), r.get("neighborhood", "")]
    ct = r.get("cuisine_tags")
    if ct and isinstance(ct, dict):
        parts.append(ct.get("primary", ""))
        parts.extend(ct.get("secondary", []))
    parts.extend(r.get("vibe_tags", []) or [])
    if r.get("price_range"):
        parts.append(r["price_range"])
    if r.get("menu_summary"):
        parts.append(r["menu_summary"][:80])
    parts.extend(r.get("specialties", []) or [])
    return " ".join(str(p) for p in parts if p)


def normalise(r: dict, nb_name: str) -> dict:
    """Fill in any missing required fields."""
    if not r.get("id"):
        r["id"] = str(uuid.uuid4())
    r.setdefault("city", "Amsterdam")
    r.setdefault("country", "NL")
    r.setdefault("neighborhood", nb_name)
    r.setdefault("is_open", True)
    r.setdefault("closed_reason", None)
    r.setdefault("data_quality_flags", None)
    r.setdefault("data_quality_notes", None)
    r.setdefault("created_at", "2026-04-07T00:00:00Z")
    r.setdefault("last_verified_date", "2026-03-15")

    coords = r.get("coordinates", {}) or {}
    if not r.get("geocodes"):
        r["geocodes"] = {"main": {"latitude": coords.get("lat"), "longitude": coords.get("lng")}}
    if not r.get("location"):
        r["location"] = {"formatted_address": r.get("address", ""), "locality": "Amsterdam", "country": "NL"}

    phone = r.get("phone") or r.get("tel")
    r["tel"] = phone
    r["phone"] = phone

    website = r.get("website") or r.get("website_url")
    r["website"] = website
    r["website_url"] = website

    if not r.get("categories"):
        r["categories"] = [{"id": 13065, "name": "Restaurant", "short_name": "Restaurant"}]

    pr = r.get("price_range", "")
    if not r.get("price"):
        r["price"] = len(pr) if pr else 2

    if not r.get("hours"):
        oh = r.get("opening_hours", {}) or {}
        days = [f"{d[:3].capitalize()}: {h}" for d, h in oh.items() if h and h != "closed" and h is not None]
        r["hours"] = {"display": "; ".join(days)} if days else {"display": "See website for hours"}

    r["embedding_text"] = generate_embedding_text(r)
    return r


# ---------------------------------------------------------------------------
# Progress persistence
# ---------------------------------------------------------------------------


def load_progress() -> list:
    if PROGRESS_PATH.exists():
        try:
            data = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
            print(f"Loaded {len(data)} records from progress file.")
            return data
        except Exception as e:
            print(f"Could not load progress: {e}")
    return []


def save_progress(records: list) -> None:
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_PATH.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print("=" * 60)
    print("miam Restaurant Generator — 126 records (120 + 6 edge cases)")
    print("=" * 60)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    all_records = load_progress()
    existing_names: set = {r.get("name", "") for r in all_records}

    # Count per neighborhood
    nb_counts: dict = {}
    for r in all_records:
        nb = r.get("neighborhood", "?")
        nb_counts[nb] = nb_counts.get(nb, 0) + 1

    total_target = sum(nb["count"] for nb in NEIGHBORHOODS)
    total_done = sum(nb_counts.get(nb["name"], 0) for nb in NEIGHBORHOODS)
    print(f"Progress: {total_done}/{total_target} standard restaurants")

    for nb in NEIGHBORHOODS:
        nb_name = nb["name"]
        have = nb_counts.get(nb_name, 0)
        need = nb["count"] - have

        if need <= 0:
            print(f"\n[{nb_name}] Complete ({have}/{nb['count']})")
            continue

        print(f"\n{'─'*50}")
        print(f"[{nb_name}] Need {need} more (have {have}/{nb['count']})")

        cuisine_batches = nb["cuisine_batches"]
        price_batches = nb["price_batches"]
        batch_idx = have // BATCH_SIZE  # resume from where we left off

        local_count = have

        while local_count < nb["count"]:
            batch_remaining = nb["count"] - local_count
            this_batch = min(BATCH_SIZE, batch_remaining)

            cb_idx = batch_idx % len(cuisine_batches)
            pb_idx = batch_idx % len(price_batches)
            cuisines = cuisine_batches[cb_idx][:this_batch]
            prices = price_batches[pb_idx][:this_batch]

            label = f"{nb_name} B{batch_idx+1}"
            print(f"\n  Batch {batch_idx+1}: {this_batch} restaurants | {cuisines} | {prices}")

            prompt = build_prompt(nb, cuisines, prices, this_batch, existing_names)
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]

            raw = call_mistral(messages, label)
            if not raw:
                print(f"  [{label}] Skipping batch after failed retries.")
                batch_idx += 1
                continue

            records = extract_array(raw)
            if not records:
                print(f"  [{label}] Could not parse any records.")
                batch_idx += 1
                continue

            added = 0
            for r in records:
                if not isinstance(r, dict):
                    continue
                name = r.get("name", "")
                if name in existing_names:
                    continue
                r = normalise(r, nb_name)
                all_records.append(r)
                existing_names.add(name)
                local_count += 1
                added += 1

            print(f"  Added {added} records. Neighborhood total: {local_count}/{nb['count']}, Overall: {len(all_records)}/{total_target}")
            save_progress(all_records)
            batch_idx += 1

            if local_count < nb["count"]:
                time.sleep(2)  # gentle rate limiting

    # Post-process: regenerate embedding_text
    print("\nRegenerating embedding_text for all records...")
    for r in all_records:
        r["embedding_text"] = generate_embedding_text(r)

    # Add edge cases
    ec_names = {ec["name"] for ec in EDGE_CASES}
    all_records = [r for r in all_records if r.get("name") not in ec_names]
    all_records.extend(EDGE_CASES)
    print(f"Added {len(EDGE_CASES)} edge cases. Total: {len(all_records)}")

    # Wrap in FSQ envelope
    output = {
        "results": all_records,
        "context": {
            "geo_bounds": {
                "circle": {
                    "center": {"latitude": 52.3676, "longitude": 4.9041},
                    "radius": 10000,
                }
            }
        },
    }

    OUTPUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"DONE! {len(all_records)} records saved to:")
    print(f"  {OUTPUT_PATH}")

    # Summary
    open_ct = sum(1 for r in all_records if r.get("is_open", True))
    price_dist: dict = {}
    nb_dist: dict = {}
    cuisine_dist: dict = {}
    for r in all_records:
        p = r.get("price_range", "?") or "?"
        price_dist[p] = price_dist.get(p, 0) + 1
        nb = r.get("neighborhood", "?")
        nb_dist[nb] = nb_dist.get(nb, 0) + 1
        ct = r.get("cuisine_tags")
        if ct and isinstance(ct, dict):
            c = ct.get("primary", "?")
            cuisine_dist[c] = cuisine_dist.get(c, 0) + 1

    print(f"\nOpen: {open_ct} | Closed: {len(all_records) - open_ct}")
    print("\nPrice distribution:")
    for p, c in sorted(price_dist.items()):
        print(f"  {p}: {c}")
    print("\nBy neighborhood:")
    for nb, n in sorted(nb_dist.items(), key=lambda x: -x[1]):
        print(f"  {nb}: {n}")
    print("\nTop cuisines:")
    for c, n in sorted(cuisine_dist.items(), key=lambda x: -x[1])[:12]:
        print(f"  {c}: {n}")
    print("=" * 60)


if __name__ == "__main__":
    main()
