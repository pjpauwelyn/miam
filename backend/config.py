"""
Application configuration — loaded from environment variables.

Required for Phase 0:
- MISTRAL_API_KEY
- SUPABASE_URL + SUPABASE_ANON_KEY + SUPABASE_SERVICE_ROLE_KEY

All Tier 2 API keys are optional and locked behind TIER2_APPROVED.
"""
from __future__ import annotations

from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Required — Mistral AI
    MISTRAL_API_KEY: str

    # Required — Supabase
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # PostgreSQL direct connection (used when available; Supabase REST fallback otherwise)
    DATABASE_URL: str = ""

    # App config
    ENV: str = "development"
    LOG_LEVEL: str = "debug"

    # Data tier
    DATA_TIER: int = 0
    TIER2_APPROVED: bool = False

    # Data source for retrieval: mock | open | combined
    DATA_SOURCE: str = "mock"

    # Tier 2 paid APIs (Phase 7+ only — DO NOT CONFIGURE without stakeholder approval)
    FOURSQUARE_API_KEY: Optional[str] = None
    GOOGLE_PLACES_API_KEY: Optional[str] = None
    TRIPADVISOR_API_KEY: Optional[str] = None
    EDAMAM_APP_ID: Optional[str] = None
    EDAMAM_APP_KEY: Optional[str] = None

    @property
    def supabase_rest_headers(self) -> dict[str, str]:
        """Headers for Supabase REST API calls."""
        key = self.SUPABASE_SERVICE_ROLE_KEY or self.SUPABASE_ANON_KEY
        return {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        # Search path: CWD first, then backend dir
        extra = "ignore"


settings = Settings()
