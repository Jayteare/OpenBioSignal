from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ExtractedClaim(BaseModel):
    """Structured evidence claim extracted from a ranked chunk."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    document_id: str
    chunk_id: str
    claim_text: str
    stance: str | None = None
    relevance: str | None = None
    study_type: str | None = None
    population: str | None = None
    intervention_or_exposure: str | None = None
    comparator: str | None = None
    outcome: str | None = None
    direction_of_effect: str | None = None
    limitations: str | None = None
    uncertainty_note: str | None = None
    evidence_span: str | None = None
    rationale: str | None = None
    stance_adjustment_note: str | None = None
    claim_repair_note: str | None = None
    document_title: str | None = None
    pmid: str | None = None
    retrieval_score: float | None = None
    evaluation_relevance_score: float | None = None
    evaluation_faithfulness_score: float | None = None
    evaluation_stance_fit_score: float | None = None
    evaluation_specificity_score: float | None = None
    evaluation_overall_score: float | None = None
    evaluation_verdict: str | None = None
    evaluation_strengths: list[str] = Field(default_factory=list)
    evaluation_weaknesses: list[str] = Field(default_factory=list)


class ClaimsExtractionResponse(BaseModel):
    """Summary of claim extraction for a research run."""

    run_id: str
    question: str
    chunks_considered: int
    claims_created: int
    claims: list[ExtractedClaim] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class RunClaimsResponse(BaseModel):
    """Collection of persisted claims for a research run."""

    run_id: str
    question: str
    claims_count: int
    claims: list[ExtractedClaim] = Field(default_factory=list)


class ClaimEvaluationSummary(BaseModel):
    """Compact aggregate summary of persisted claim evaluations for a run."""

    claims_total: int
    claims_evaluated: int
    average_relevance_score: float | None = None
    average_faithfulness_score: float | None = None
    average_stance_fit_score: float | None = None
    average_specificity_score: float | None = None
    average_overall_score: float | None = None
    verdict_counts: dict[str, int] = Field(default_factory=dict)
    weak_claim_count: int = 0
    strong_claim_count: int = 0


class ClaimsEvaluationResponse(BaseModel):
    """Summary returned after evaluating persisted claims for a run."""

    run_id: str
    claims_total: int
    claims_evaluated: int
    average_overall_score: float | None = None
    verdict_counts: dict[str, int] = Field(default_factory=dict)
    evaluation_summary: ClaimEvaluationSummary
    errors: list[str] = Field(default_factory=list)


class RunClaimEvaluationsResponse(BaseModel):
    """Persisted claim evaluations for a run."""

    run_id: str
    question: str
    evaluation_summary: ClaimEvaluationSummary
    claims: list[ExtractedClaim] = Field(default_factory=list)
