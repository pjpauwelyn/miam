"""
Load test profiles into Supabase user_profiles table.
"""
import asyncio
import json
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
from config import settings

PROFILES_PATH = PROJECT_ROOT / "data" / "profiles" / "all_profiles.json"


def get_headers():
    key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_ANON_KEY
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation",
    }


async def main():
    if not PROFILES_PATH.exists():
        print(f"ERROR: {PROFILES_PATH} not found. Run generate_profiles.py first.")
        sys.exit(1)

    with open(PROFILES_PATH, "r", encoding="utf-8") as f:
        profiles = json.load(f)

    print(f"Loading {len(profiles)} profiles into Supabase...")

    headers = get_headers()
    base_url = f"{settings.SUPABASE_URL}/rest/v1"

    rows = []
    for p in profiles:
        user_id = p.get("user_id")
        rows.append({
            "user_id": user_id,
            "profile_status": "complete" if p.get("onboarding_complete") else "incomplete",
            "profile_data": p,
        })

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/user_profiles",
            headers=headers,
            json=rows,
            timeout=30.0,
        )
        if resp.status_code in (200, 201):
            print(f"Successfully seeded {len(rows)} profiles")
            for r in rows:
                print(f"  user_id={r['user_id']} status={r['profile_status']}")
        else:
            print(f"Seed failed: {resp.status_code} {resp.text[:500]}")


if __name__ == "__main__":
    asyncio.run(main())
