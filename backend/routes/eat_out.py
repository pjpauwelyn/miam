from fastapi import APIRouter
from pydantic import BaseModel
from typing import Any

router = APIRouter()


class EatOutQueryRequest(BaseModel):
    user_id: str
    query: str
    session_id: str | None = None
    location: dict[str, float] | None = None  # {"lat": ..., "lon": ...}
    radius_km: float = 5.0
    filters: dict[str, Any] | None = None


@router.post("/query", summary="Restaurant discovery query")
async def eat_out_query(body: EatOutQueryRequest) -> dict[str, Any]:
    """
    Processes a natural-language query for restaurant recommendations.
    Pipeline:
      1. Parse query → QueryOntology via LLM
      2. Fuse with PersonalOntology → FusedOntology
      3. Retrieve matching restaurants via vector search + geo filter
      4. Rank, explain, and return top results
    """
    return {"status": "not_implemented"}
