from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

import json

from app.db.models import Brief, Chunk, Claim, Document, ResearchRun
from app.db.session import get_db
from app.services.claim_evaluator import build_run_evaluation_summary, get_claim_evaluation_data
from app.services.pipeline_debug import build_pipeline_debug_payload
from app.services.retriever import compute_chunk_ranking_breakdown
from app.services.run_diagnostics import build_run_diagnostics

router = APIRouter(tags=["ui"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """Render the landing page with a starter submission form."""

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"page_title": "OpenBioSignal"},
    )


@router.get("/runs", response_class=HTMLResponse)
def runs_index(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """Render a list of saved research runs."""

    runs = db.scalars(select(ResearchRun).order_by(desc(ResearchRun.created_at))).all()
    run_cards: list[dict[str, object]] = []
    for run in runs:
        documents_count = len(run.documents)
        chunks_count = sum(len(document.chunks) for document in run.documents)
        claims_count = sum(len(chunk.claims) for document in run.documents for chunk in document.chunks)
        run_cards.append(
            {
                "id": run.id,
                "question": run.question,
                "status": run.status,
                "created_at": run.created_at,
                "documents_count": documents_count,
                "chunks_count": chunks_count,
                "claims_count": claims_count,
                "has_brief": run.brief is not None,
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="runs.html",
        context={
            "page_title": "Research Runs",
            "runs": run_cards,
        },
    )


@router.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(
    request: Request,
    run_id: str,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Render a persisted research run."""

    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    documents = db.scalars(
        select(Document).where(Document.run_id == run.id).order_by(Document.pubdate.desc(), Document.title.asc())
    ).all()
    chunks = db.scalars(
        select(Chunk).where(Chunk.run_id == run.id).order_by(Chunk.document_id.asc(), Chunk.chunk_index.asc())
    ).all()
    top_chunks = db.scalars(
        select(Chunk)
        .where(Chunk.run_id == run.id)
        .order_by(desc(Chunk.retrieval_score), Chunk.document_id.asc(), Chunk.chunk_index.asc())
        .limit(10)
    ).all()
    claims = db.scalars(
        select(Claim)
        .join(Chunk, Claim.chunk_id == Chunk.id)
        .where(Claim.run_id == run.id)
        .order_by(desc(Chunk.retrieval_score), Chunk.chunk_index.asc(), Claim.id.asc())
    ).all()
    brief = db.scalars(select(Brief).where(Brief.run_id == run.id)).first()

    chunk_counts_by_document: dict[str, int] = {}
    chunk_previews_by_document: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        chunk_counts_by_document[chunk.document_id] = chunk_counts_by_document.get(chunk.document_id, 0) + 1
        previews = chunk_previews_by_document.setdefault(chunk.document_id, [])
        if len(previews) < 2:
            previews.append(chunk)

    document_titles_by_id = {document.id: document.title for document in documents}
    document_pmids_by_id = {document.id: document.pmid for document in documents}
    abstracts_count = sum(1 for document in documents if document.abstract and document.abstract.strip())
    ranked_chunks_count = sum(1 for chunk in chunks if chunk.retrieval_score is not None)
    retrieval_scores_by_chunk_id = {chunk.id: chunk.retrieval_score for chunk in chunks}
    top_chunk_rank_breakdowns = {
        chunk.id: compute_chunk_ranking_breakdown(run.question, chunk.text, chunk.section) for chunk in top_chunks
    }
    claim_rows = [_build_claim_row(claim) for claim in claims]
    diagnostics = build_run_diagnostics(run, db)
    pipeline_debug = build_pipeline_debug_payload(run)
    evaluation_summary = build_run_evaluation_summary(claims)
    evaluated_claims = sorted(
        [claim_row for claim_row in claim_rows if claim_row["evaluation_overall_score"] is not None],
        key=lambda claim_row: (
            float(claim_row["evaluation_overall_score"]),
            -(float(claim_row["retrieval_score"]) if claim_row["retrieval_score"] is not None else 0.0),
            str(claim_row["id"]),
        ),
    )
    brief_data = None
    if brief is not None:
        brief_data = {
            "direct_answer": brief.direct_answer or "",
            "summary": brief.summary,
            "supporting_findings": _deserialize_string_list(brief.supporting_findings),
            "conflicting_findings": _deserialize_string_list(brief.conflicting_findings),
            "caveats": _deserialize_string_list(brief.caveats),
            "evidence_table_rows": _deserialize_rows(brief.evidence_table_json),
            "markdown_report": brief.markdown_report or "",
        }

    return templates.TemplateResponse(
        request=request,
        name="run.html",
        context={
            "page_title": "Research Run",
            "run_id": run.id,
            "question": run.question,
            "status": run.status,
            "documents": documents,
            "documents_count": len(documents),
            "abstracts_count": abstracts_count,
            "chunk_counts_by_document": chunk_counts_by_document,
            "chunk_previews_by_document": chunk_previews_by_document,
            "chunks_count": len(chunks),
            "ranked_chunks_count": ranked_chunks_count,
            "top_chunks": top_chunks,
            "top_chunk_rank_breakdowns": top_chunk_rank_breakdowns,
            "claims": claim_rows,
            "claims_count": len(claim_rows),
            "evaluated_claims": evaluated_claims,
            "evaluation_summary": evaluation_summary,
            "diagnostics": diagnostics,
            "pipeline_debug": pipeline_debug,
            "brief": brief_data,
            "document_titles_by_id": document_titles_by_id,
            "document_pmids_by_id": document_pmids_by_id,
            "retrieval_scores_by_chunk_id": retrieval_scores_by_chunk_id,
        },
    )


def _deserialize_string_list(value: str | None) -> list[str]:
    """Deserialize a JSON-string list into a Python list."""

    if not value:
        return []

    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        payload = None

    if isinstance(payload, list):
        return [str(item).strip() for item in payload if str(item).strip()]

    text = value.strip()
    return [text] if text else []


def _deserialize_rows(value: str | None) -> list[dict]:
    """Deserialize stored evidence table rows."""

    if not value:
        return []

    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        payload = []

    return payload if isinstance(payload, list) else []


def _build_claim_row(claim: Claim) -> dict[str, object]:
    """Flatten ORM claim data plus parsed evaluation fields for template rendering."""

    evaluation = get_claim_evaluation_data(claim)
    return {
        "id": claim.id,
        "run_id": claim.run_id,
        "document_id": claim.document_id,
        "chunk_id": claim.chunk_id,
        "claim_text": claim.claim_text,
        "stance": claim.stance,
        "relevance": claim.relevance,
        "study_type": claim.study_type,
        "outcome": claim.outcome,
        "uncertainty_note": claim.uncertainty_note,
        "evidence_span": claim.evidence_span,
        "rationale": claim.rationale,
        "stance_adjustment_note": claim.stance_adjustment_note,
        "claim_repair_note": claim.claim_repair_note,
        "pmid": claim.document.pmid if claim.document else None,
        "retrieval_score": claim.chunk.retrieval_score if claim.chunk else None,
        "evaluation_relevance_score": evaluation["relevance_score"],
        "evaluation_faithfulness_score": evaluation["faithfulness_score"],
        "evaluation_stance_fit_score": evaluation["stance_fit_score"],
        "evaluation_specificity_score": evaluation["specificity_score"],
        "evaluation_overall_score": evaluation["overall_score"],
        "evaluation_verdict": evaluation["verdict"],
        "evaluation_strengths": evaluation["strengths"],
        "evaluation_weaknesses": evaluation["weaknesses"],
    }
