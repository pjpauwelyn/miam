from fastapi import APIRouter, HTTPException
from typing import Any

router = APIRouter()


@router.get("/trending", summary="Trending recipes and restaurants")
async def trending(
    limit: int = 10,
    mode: str = "all",  # "all" | "eat_in" | "eat_out"
) -> dict[str, Any]:
    """
    Returns trending items based on aggregate feedback signals.
    Results are personalised when a valid user_id header is present.
    """
    raise HTTPException(status_code=501, detail="Not implemented")


@router.get("/seasonal", summary="Seasonally appropriate suggestions")
async def seasonal(
    limit: int = 10,
    hemisphere: str = "north",  # "north" | "south"
) -> dict[str, Any]:
    """
    Returns recipes and restaurants that match the current season
    and available seasonal produce in the user's hemisphere.
    """
    raise HTTPException(status_code=501, detail="Not implemented")
