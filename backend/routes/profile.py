import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from middleware.auth import get_current_user_id
from services.llm_router import LLMOperation, call_llm

logger = logging.getLogger(__name__)

router = APIRouter()


class ProfileUpdateRequest(BaseModel):
    user_id: str
    updates: dict[str, Any]


class ProfileCompileRequest(BaseModel):
    user_id: str
    answers: dict[str, Any]
    system_prompt: str
    user_prompt: str


@router.get("/", summary="Retrieve current user profile")
async def get_profile() -> dict[str, Any]:
    """Returns the full PersonalOntology for the authenticated user."""
    return {"status": "not_implemented"}


@router.put("/update", summary="Update profile fields")
async def update_profile(body: ProfileUpdateRequest) -> dict[str, Any]:
    """
    Applies a partial update to the user's profile.
    Re-generates embeddings for any updated preference vectors.
    """
    return {"status": "not_implemented"}


@router.get("/taste-profile", summary="Return human-readable taste summary")
async def taste_profile() -> dict[str, Any]:
    """
    Derives a natural-language taste profile summary from the PersonalOntology,
    suitable for display in the app's profile screen.
    """
    return {"status": "not_implemented"}


@router.post("/compile", summary="Compile profile via LLM")
async def compile_profile(body: ProfileCompileRequest, auth_user_id: Optional[str] = Depends(get_current_user_id)) -> dict[str, Any]:
    """
    Accepts onboarding answers + prompt, calls Mistral to compile
    free-text answers into structured profile enrichments.
    """
    if auth_user_id:
        body.user_id = auth_user_id
    try:
        result = await call_llm(
            operation=LLMOperation.ONBOARDING_SUMMARY,
            messages=[
                {"role": "system", "content": body.system_prompt},
                {"role": "user", "content": body.user_prompt},
            ],
            temperature=0.3,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
        import json
        return json.loads(result)
    except Exception as exc:
        logger.error("Profile compile failed for user_id=%s: %s", body.user_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Profile compilation failed. Please try again.")
