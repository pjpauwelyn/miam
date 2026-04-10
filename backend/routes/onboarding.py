from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any

router = APIRouter()


class OnboardingStartRequest(BaseModel):
    user_id: str
    locale: str = "en"


class OnboardingAnswerRequest(BaseModel):
    user_id: str
    question_id: str
    answer: Any


class OnboardingCompleteRequest(BaseModel):
    user_id: str


@router.post("/start", summary="Begin onboarding flow")
async def start_onboarding(body: OnboardingStartRequest) -> dict[str, Any]:
    """
    Initialises an onboarding session for a new user.
    Returns the first question in the preference-discovery sequence.
    """
    raise HTTPException(status_code=501, detail="Not implemented")


@router.post("/answer", summary="Submit an onboarding answer")
async def submit_answer(body: OnboardingAnswerRequest) -> dict[str, Any]:
    """
    Records a single onboarding answer and returns the next question,
    or signals completion when all questions have been answered.
    """
    raise HTTPException(status_code=501, detail="Not implemented")


@router.post("/complete", summary="Finalise onboarding and build initial profile")
async def complete_onboarding(body: OnboardingCompleteRequest) -> dict[str, Any]:
    """
    Triggers profile synthesis from collected onboarding answers.
    Generates the initial PersonalOntology and stores embeddings.
    """
    raise HTTPException(status_code=501, detail="Not implemented")
