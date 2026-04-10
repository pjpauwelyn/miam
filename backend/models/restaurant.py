from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class RestaurantCoordinates(BaseModel):
    lat: Optional[float] = Field(None, description="WGS84 latitude, e.g. 52.3676")
    lng: Optional[float] = Field(None, description="WGS84 longitude, e.g. 4.9041")


class RestaurantCuisineTags(BaseModel):
    primary: str
    secondary: list[str] = Field(default_factory=list)


class RestaurantOpeningHours(BaseModel):
    monday: Optional[str] = Field(
        default=None,
        description="E.g. '12:00-22:00' or 'closed'"
    )
    tuesday: Optional[str] = None
    wednesday: Optional[str] = None
    thursday: Optional[str] = None
    friday: Optional[str] = None
    saturday: Optional[str] = None
    sunday: Optional[str] = None


class RestaurantMenuItem(BaseModel):
    name: str
    description: str = Field(..., description="1-2 sentences")
    price_eur: float
    course: str = Field(
        ...,
        description="starter | main | dessert | drink | side | sharing"
    )
    dietary_tags: list[str] = Field(default_factory=list)


class RestaurantDietaryOptions(BaseModel):
    vegan_ok: bool = False
    vegetarian_ok: bool = False
    halal_ok: bool = False
    gluten_free_ok: bool = False
    kosher_ok: bool = False


class RestaurantDataQualityFlags(BaseModel):
    missing_menu: bool = False
    missing_hours: bool = False
    missing_phone: bool = False
    missing_website: bool = False
    unverified_dietary: bool = False


class RestaurantDocument(BaseModel):
    """
    Canonical restaurant document stored in the miam database and indexed for RAG retrieval.
    Schema mirrors FSQ OS fields where they overlap, with miam-specific extensions.
    """
    id: UUID = Field(default_factory=uuid4)

    # FSQ OS alignment
    fsq_place_id: Optional[str] = Field(
        default=None,
        description="From Foursquare Open Source Places, if available"
    )

    # Identity & location
    name: str
    address: str = Field(
        ...,
        description="Full Dutch street address: straatnaam huisnummer, postcode Amsterdam"
    )
    neighborhood: str = Field(
        ...,
        description="Controlled vocabulary: Jordaan | De Pijp | Centrum | Oud-Zuid | Noord | Oost | Nieuw-West | Watergraafsmeer | Buitenveldert | IJburg"
    )
    city: str = "Amsterdam"
    country: str = "NL"

    # Classification
    cuisine_tags: RestaurantCuisineTags
    vibe_tags: list[str] = Field(
        default_factory=list,
        description="Min 3, from controlled vocabulary: romantic | casual | family-friendly | date-night | business-lunch | group-dining | solo-friendly | late-night | brunch-spot | terrace | canal-side | trendy | hidden-gem | tourist-trap | local-favorite | quick-bite | fine-dining | wine-bar | live-music | cultural-experience | instagram-worthy | no-reservation-needed | outdoor-seating | cozy | minimalist | traditional | modern | rustic | lively | quiet"
    )
    price_range: str = Field(
        ...,
        description="€ | €€ | €€€ | €€€€"
    )

    # Geo
    coordinates: RestaurantCoordinates

    # Contact
    phone: Optional[str] = Field(default=None, description="+31 format")
    website_url: Optional[str] = None

    # Hours
    opening_hours: RestaurantOpeningHours = Field(default_factory=RestaurantOpeningHours)

    # Menu
    menu_summary: Optional[str] = Field(
        default=None,
        description="150-300 word paragraph describing menu philosophy and key dishes, or null for missing-menu edge case"
    )
    menu_items: list[RestaurantMenuItem] = Field(default_factory=list)

    # Reviews & ratings
    review_summary: Optional[str] = Field(
        default=None,
        description="200-400 words, synthesized from multiple review perspectives, written in third-person"
    )
    review_count_estimate: Optional[int] = None
    rating_estimate: Optional[float] = Field(
        default=None, ge=1.0, le=5.0,
        description="One decimal place"
    )

    # Highlights
    specialties: list[str] = Field(
        default_factory=list,
        description="3-5 dish names"
    )

    # Dietary options
    dietary_options: RestaurantDietaryOptions = Field(default_factory=RestaurantDietaryOptions)

    # Reservations & status
    reservation_url: Optional[str] = None
    is_open: bool = Field(
        default=True,
        description="True = currently operating; False = permanently closed but retained for edge case testing"
    )
    closed_reason: Optional[str] = Field(
        default=None,
        description="Only populate if is_open=False — e.g. 'Permanently closed November 2024', 'Owner retired'"
    )
    last_verified_date: Optional[str] = Field(
        default=None,
        description="ISO 8601 date string"
    )

    # Data quality
    data_quality_score: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="1.0 = all fields populated and verified, 0.0 = name and coordinates only"
    )
    data_quality_flags: Optional[RestaurantDataQualityFlags] = None
    data_quality_notes: Optional[str] = None

    # RAG embedding
    embedding_text: str = Field(
        ...,
        description=(
            "Pre-computed concatenation of name + neighborhood + cuisine_tags "
            "+ vibe_tags + menu_summary + review_summary + specialties"
        )
    )

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
