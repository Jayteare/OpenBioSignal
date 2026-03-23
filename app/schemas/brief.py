from __future__ import annotations

from pydantic import BaseModel, Field


class EvidenceTableRow(BaseModel):
    """Normalized inspectable evidence row derived from one persisted claim."""

    claim_id: str
    document_id: str
    chunk_id: str
    document_title: str | None = None
    pmid: str | None = None
    stance: str | None = None
    relevance: str | None = None
    study_type: str | None = None
    population: str | None = None
    intervention_or_exposure: str | None = None
    comparator: str | None = None
    outcome: str | None = None
    direction_of_effect: str | None = None
    limitations: list[str] = Field(default_factory=list)
    uncertainty_note: str | None = None
    evidence_span: str | None = None
    claim_text: str
    retrieval_score: float | None = None


class EvidenceBrief(BaseModel):
    """Persisted grounded evidence brief for a research run."""

    id: str
    run_id: str
    direct_answer: str
    summary: str
    supporting_findings: list[str] = Field(default_factory=list)
    conflicting_findings: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class BriefGenerationResponse(BaseModel):
    """Summary of evidence-brief generation for a research run."""

    run_id: str
    question: str
    brief_generated: bool
    brief: EvidenceBrief | None = None
    error: str | None = None


class EvidenceTableResponse(BaseModel):
    """Stored evidence table for a research run."""

    run_id: str
    question: str
    rows: list[EvidenceTableRow] = Field(default_factory=list)


class MarkdownReportResponse(BaseModel):
    """Stored markdown report for a research run."""

    run_id: str
    question: str
    markdown_report: str
