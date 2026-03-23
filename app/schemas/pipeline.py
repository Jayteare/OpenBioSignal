from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PipelineRunResponse(BaseModel):
    """Summary of running the synchronous pipeline for a saved run."""

    run_id: str
    question: str
    status: str
    documents_total: int
    abstracts_available: int
    chunks_total: int
    ranked_chunks: int
    claims_total: int
    brief_generated: bool
    brief_id: str | None = None
    steps: dict[str, dict[str, Any]] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class PipelineDebugResponse(BaseModel):
    """Latest persisted pipeline debug snapshot for a saved run."""

    run_id: str
    question: str
    status: str
    has_pipeline_debug: bool
    last_pipeline_run_at: datetime | None = None
    documents_total: int = 0
    abstracts_available: int = 0
    chunks_total: int = 0
    ranked_chunks: int = 0
    claims_total: int = 0
    brief_generated: bool = False
    brief_id: str | None = None
    steps: dict[str, dict[str, Any]] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    error_count: int = 0
    claim_extraction_attempted: bool = False
    claim_extraction_failed: bool = False
