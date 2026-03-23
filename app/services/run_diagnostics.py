"""Helpers for compact run-level diagnostics and quality checks."""

from __future__ import annotations

import json
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Brief, Chunk, Claim, Document, ResearchRun
from app.services.pipeline_debug import build_pipeline_debug_payload


def build_run_diagnostics(run: ResearchRun, db: Session) -> dict:
    """Build a compact diagnostics summary for a persisted run."""

    documents = db.scalars(select(Document).where(Document.run_id == run.id)).all()
    chunks = db.scalars(select(Chunk).where(Chunk.run_id == run.id)).all()
    claims = db.scalars(select(Claim).where(Claim.run_id == run.id)).all()
    brief = db.scalars(select(Brief).where(Brief.run_id == run.id)).first()
    pipeline_debug = build_pipeline_debug_payload(run)
    latest_pipeline_blocker = _infer_latest_pipeline_blocker(pipeline_debug.get("errors", []))

    documents_total = len(documents)
    documents_with_abstracts = sum(1 for document in documents if document.abstract and document.abstract.strip())
    chunks_total = len(chunks)
    ranked_chunks = [chunk for chunk in chunks if chunk.retrieval_score is not None]
    ranked_chunks_total = len(ranked_chunks)
    chunks_missing_scores = chunks_total - ranked_chunks_total

    claimed_chunk_ids = {claim.chunk_id for claim in claims}
    claimed_chunks_total = len(claimed_chunk_ids)
    unclaimed_ranked_chunks_total = sum(1 for chunk in ranked_chunks if chunk.id not in claimed_chunk_ids)
    claims_missing_evidence_span = sum(1 for claim in claims if not (claim.evidence_span and claim.evidence_span.strip()))

    claimed_chunk_scores = [
        chunk.retrieval_score
        for chunk in ranked_chunks
        if chunk.id in claimed_chunk_ids and chunk.retrieval_score is not None
    ]
    stance_counts = {stance: 0 for stance in ("supports", "weakens", "mixed", "background")}
    for claim in claims:
        stance = claim.stance or "background"
        if stance not in stance_counts:
            stance_counts[stance] = 0
        stance_counts[stance] += 1

    diagnostics = {
        "run_id": run.id,
        "status": run.status,
        "documents_total": documents_total,
        "documents_with_abstracts": documents_with_abstracts,
        "chunks_total": chunks_total,
        "ranked_chunks_total": ranked_chunks_total,
        "claims_total": len(claims),
        "claimed_chunks_total": claimed_chunks_total,
        "unclaimed_ranked_chunks_total": unclaimed_ranked_chunks_total,
        "brief_exists": brief is not None,
        "markdown_report_exists": bool(brief and brief.markdown_report),
        "evidence_table_row_count": _count_evidence_table_rows(brief),
        "average_retrieval_score_for_claimed_chunks": round(mean(claimed_chunk_scores), 4) if claimed_chunk_scores else None,
        "max_retrieval_score": max((chunk.retrieval_score for chunk in ranked_chunks), default=None),
        "min_retrieval_score": min((chunk.retrieval_score for chunk in ranked_chunks), default=None),
        "chunks_missing_scores": chunks_missing_scores,
        "claims_missing_evidence_span": claims_missing_evidence_span,
        "pipeline_debug_exists": pipeline_debug["has_pipeline_debug"],
        "latest_pipeline_error_count": pipeline_debug["error_count"],
        "last_pipeline_run_at": pipeline_debug["last_pipeline_run_at"],
        "claim_extraction_attempted": pipeline_debug["claim_extraction_attempted"],
        "claim_extraction_failed": pipeline_debug["claim_extraction_failed"],
        "latest_pipeline_quota_issue": bool(latest_pipeline_blocker),
        "latest_pipeline_blocker": latest_pipeline_blocker,
        "claims_by_stance": stance_counts,
        "warnings": _build_warnings(
            documents_total=documents_total,
            documents_with_abstracts=documents_with_abstracts,
            chunks_total=chunks_total,
            ranked_chunks_total=ranked_chunks_total,
            claims_total=len(claims),
            brief_exists=brief is not None,
            claims_missing_evidence_span=claims_missing_evidence_span,
            chunks_missing_scores=chunks_missing_scores,
            latest_pipeline_error_count=pipeline_debug["error_count"],
            claim_extraction_failed=pipeline_debug["claim_extraction_failed"],
        ),
    }
    return diagnostics


def _count_evidence_table_rows(brief: Brief | None) -> int:
    """Count evidence-table rows persisted on a brief."""

    if brief is None or not brief.evidence_table_json:
        return 0

    try:
        payload = json.loads(brief.evidence_table_json)
    except json.JSONDecodeError:
        payload = []

    return len(payload) if isinstance(payload, list) else 0


def _build_warnings(
    *,
    documents_total: int,
    documents_with_abstracts: int,
    chunks_total: int,
    ranked_chunks_total: int,
    claims_total: int,
    brief_exists: bool,
    claims_missing_evidence_span: int,
    chunks_missing_scores: int,
    latest_pipeline_error_count: int,
    claim_extraction_failed: bool,
) -> list[str]:
    """Return simple human-readable warnings for incomplete runs."""

    warnings: list[str] = []
    if documents_total == 0:
        warnings.append("No documents found for this run.")
    if documents_with_abstracts == 0:
        warnings.append("No abstracts have been fetched yet.")
    if chunks_total == 0:
        warnings.append("No chunks have been created yet.")
    if ranked_chunks_total == 0:
        warnings.append("No chunks have been ranked yet.")
    if claims_total == 0:
        warnings.append("No claims have been extracted yet.")
    if not brief_exists:
        warnings.append("No brief has been generated yet.")
    if claims_missing_evidence_span > 0:
        warnings.append(f"{claims_missing_evidence_span} claims are missing an evidence span.")
    if chunks_missing_scores > 0 and chunks_total > 0:
        warnings.append(f"{chunks_missing_scores} chunks are missing retrieval scores.")
    if latest_pipeline_error_count > 0:
        warnings.append(f"The latest pipeline run recorded {latest_pipeline_error_count} non-fatal errors.")
    if claim_extraction_failed:
        warnings.append("The latest pipeline run recorded claim extraction failures.")
    return warnings


def _infer_latest_pipeline_blocker(errors: list[str]) -> str | None:
    """Infer a prominent user-facing blocker from latest pipeline errors."""

    quota_message = "Z.AI API quota or billing limit reached. Check your API key, billing, credits, and model access."
    for error in errors:
        if quota_message in error:
            return "Claim or brief generation is currently blocked by Z.AI quota/billing limits."
    return None
