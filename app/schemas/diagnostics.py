from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RunDiagnosticsResponse(BaseModel):
    """Compact diagnostics summary for a saved research run."""

    run_id: str
    status: str
    documents_total: int
    documents_with_abstracts: int
    chunks_total: int
    ranked_chunks_total: int
    claims_total: int
    claimed_chunks_total: int
    unclaimed_ranked_chunks_total: int
    brief_exists: bool
    markdown_report_exists: bool
    evidence_table_row_count: int
    average_retrieval_score_for_claimed_chunks: float | None = None
    max_retrieval_score: float | None = None
    min_retrieval_score: float | None = None
    chunks_missing_scores: int
    claims_missing_evidence_span: int
    pipeline_debug_exists: bool = False
    latest_pipeline_error_count: int = 0
    last_pipeline_run_at: datetime | None = None
    claim_extraction_attempted: bool = False
    claim_extraction_failed: bool = False
    latest_pipeline_quota_issue: bool = False
    latest_pipeline_blocker: str | None = None
    claims_by_stance: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
