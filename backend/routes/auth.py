from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr
from typing import Any

router = APIRouter()


class MagicLinkRequest(BaseModel):
    email: EmailStr


class VerifyRequest(BaseModel):
    token: str
    email: EmailStr


class LogoutRequest(BaseModel):
    user_id: str


@router.post("/login", summary="Send magic link", status_code=status.HTTP_202_ACCEPTED)
async def login(body: MagicLinkRequest) -> dict[str, Any]:
    """
    Sends a magic-link email via Supabase Auth.
    The client must call POST /verify with the token from the email.
    """
    raise HTTPException(status_code=501, detail="Not implemented")


@router.post("/verify", summary="Verify magic link token")
async def verify(body: VerifyRequest) -> dict[str, Any]:
    """
    Verifies the one-time token received in the magic-link email.
    Returns a session object (access_token + refresh_token) on success.
    """
    raise HTTPException(status_code=501, detail="Not implemented")


@router.post("/logout", summary="Invalidate session")
async def logout(body: LogoutRequest) -> dict[str, Any]:
    """Invalidates the current session on Supabase Auth."""
    raise HTTPException(status_code=501, detail="Not implemented")


@router.delete("/users/{user_id}", summary="GDPR — cascade delete user")
async def delete_user(user_id: str) -> dict[str, Any]:
    """
    Permanently deletes a user and all associated data (GDPR right to erasure).
    Cascades through: profiles, sessions, feedback, embeddings.
    """
    raise HTTPException(status_code=501, detail="Not implemented")


@router.get("/users/{user_id}/export", summary="GDPR — export user data")
async def export_user(user_id: str) -> dict[str, Any]:
    """
    Returns a full export of all data held for the given user (GDPR right of access).
    """
    raise HTTPException(status_code=501, detail="Not implemented")
