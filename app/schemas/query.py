from __future__ import annotations

from pydantic import BaseModel, Field


class ResearchQuestionCreate(BaseModel):
    """Incoming request payload for creating a research run."""

    question: str = Field(..., min_length=3, description="Biomedical research question")


class ResearchRunResponse(BaseModel):
    """Starter response model for a newly created research run."""

    run_id: str
    question: str
    status: str = "created"
