from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

import json

from app.db.models import Brief, Chunk, Claim, Document, ResearchRun
from app.db.session import get_db
from app.config import get_settings
from app.schemas.brief import (
    BriefGenerationResponse,
    EvidenceBrief,
    EvidenceTableResponse,
    EvidenceTableRow,
    MarkdownReportResponse,
)
from app.schemas.chunk import (
    ChunkRecord,
    ChunkingResponse,
    DocumentChunksResponse,
    RankedChunksResponse,
    RunChunksResponse,
    TopChunksResponse,
)
from app.schemas.claim import (
    ClaimEvaluationSummary,
    ClaimsEvaluationResponse,
    ClaimsExtractionResponse,
    ExtractedClaim,
    RunClaimEvaluationsResponse,
    RunClaimsResponse,
)
from app.schemas.diagnostics import RunDiagnosticsResponse
from app.schemas.document import AbstractFetchResponse, DocumentRecord, RunDocumentsResponse, RunSearchResponse
from app.schemas.pipeline import PipelineDebugResponse, PipelineRunResponse
from app.schemas.query import ResearchQuestionCreate, ResearchRunResponse
from app.services.brief_generator import (
    build_brief_generation_error_summary,
    build_evidence_table_for_run,
    build_markdown_report_for_run,
    generate_brief_for_run,
)
from app.services.chunker import chunk_document_abstract
from app.services.claim_extractor import extract_claims_for_run
from app.services.claim_evaluator import build_run_evaluation_summary, evaluate_claims_for_run, get_claim_evaluation_data
from app.services.pubmed_search import fetch_pubmed_abstracts, search_pubmed
from app.services.retriever import compute_chunk_ranking_breakdown, rank_chunks_for_run
from app.services.pipeline_runner import run_pipeline_for_run
from app.services.pipeline_debug import build_pipeline_debug_payload
from app.services.run_diagnostics import build_run_diagnostics

router = APIRouter(prefix="/api", tags=["api"])
settings = get_settings()


def _serialize_run(run: ResearchRun) -> ResearchRunResponse:
    """Convert a run ORM object into the public response model."""

    return ResearchRunResponse(
        run_id=run.id,
        question=run.question,
        status=run.status,
    )


def _serialize_document(document: Document) -> DocumentRecord:
    """Convert a document ORM object into the public response model."""

    return DocumentRecord(
        id=document.id,
        run_id=document.run_id,
        pmid=document.pmid,
        title=document.title,
        journal=document.journal,
        pubdate=document.pubdate,
        authors=document.authors,
        source=document.source,
        source_url=document.source_url,
        abstract=document.abstract,
        has_abstract=bool(document.abstract and document.abstract.strip()),
        chunk_count=len(document.chunks),
    )


def _serialize_chunk(chunk: Chunk, query: str | None = None) -> ChunkRecord:
    """Convert a chunk ORM object into the public response model."""

    breakdown = compute_chunk_ranking_breakdown(query, chunk.text, chunk.section) if query else {}
    return ChunkRecord(
        id=chunk.id,
        run_id=chunk.run_id,
        document_id=chunk.document_id,
        document_title=chunk.document.title if chunk.document else None,
        chunk_index=chunk.chunk_index,
        section=chunk.section,
        text=chunk.text,
        retrieval_score=chunk.retrieval_score,
        lexical_score=breakdown.get("lexical_score"),
        result_signal_score=breakdown.get("result_signal_score"),
        methods_penalty=breakdown.get("methods_penalty"),
    )


def _serialize_claim(claim: Claim) -> ExtractedClaim:
    """Convert a claim ORM object into the public response model."""

    evaluation = get_claim_evaluation_data(claim)
    return ExtractedClaim(
        id=claim.id,
        run_id=claim.run_id,
        document_id=claim.document_id,
        chunk_id=claim.chunk_id,
        claim_text=claim.claim_text,
        stance=claim.stance,
        relevance=claim.relevance,
        study_type=claim.study_type,
        population=claim.population,
        intervention_or_exposure=claim.intervention_or_exposure,
        comparator=claim.comparator,
        outcome=claim.outcome,
        direction_of_effect=claim.direction_of_effect,
        limitations=claim.limitations,
        uncertainty_note=claim.uncertainty_note,
        evidence_span=claim.evidence_span,
        rationale=claim.rationale,
        stance_adjustment_note=claim.stance_adjustment_note,
        claim_repair_note=claim.claim_repair_note,
        document_title=claim.document.title if claim.document else None,
        pmid=claim.document.pmid if claim.document else None,
        retrieval_score=claim.chunk.retrieval_score if claim.chunk else None,
        evaluation_relevance_score=evaluation["relevance_score"],
        evaluation_faithfulness_score=evaluation["faithfulness_score"],
        evaluation_stance_fit_score=evaluation["stance_fit_score"],
        evaluation_specificity_score=evaluation["specificity_score"],
        evaluation_overall_score=evaluation["overall_score"],
        evaluation_verdict=evaluation["verdict"],
        evaluation_strengths=evaluation["strengths"],
        evaluation_weaknesses=evaluation["weaknesses"],
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


def _serialize_brief(brief: Brief) -> EvidenceBrief:
    """Convert a brief ORM object into the public response model."""

    return EvidenceBrief(
        id=brief.id,
        run_id=brief.run_id,
        direct_answer=brief.direct_answer or "",
        summary=brief.summary,
        supporting_findings=_deserialize_string_list(brief.supporting_findings),
        conflicting_findings=_deserialize_string_list(brief.conflicting_findings),
        caveats=_deserialize_string_list(brief.caveats),
    )


def _deserialize_evidence_rows(value: str | None) -> list[EvidenceTableRow]:
    """Deserialize evidence table JSON into response rows."""

    if not value:
        return []

    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        payload = []

    if not isinstance(payload, list):
        return []

    rows: list[EvidenceTableRow] = []
    for item in payload:
        if isinstance(item, dict):
            rows.append(EvidenceTableRow(**item))
    return rows


@router.get("/health")
def api_health() -> dict[str, str | bool]:
    """API health endpoint for local checks."""

    return {
        "status": "ok",
        "z_ai_api_key_configured": bool(settings.z_ai_api_key),
        "z_ai_model": settings.z_ai_model,
    }


@router.get("/runs/{run_id}", response_model=ResearchRunResponse)
def get_run(run_id: str, db: Session = Depends(get_db)) -> ResearchRunResponse:
    """Return a persisted research run by ID."""

    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    return _serialize_run(run)


@router.post("/runs", response_model=ResearchRunResponse)
def create_run(
    payload: ResearchQuestionCreate,
    db: Session = Depends(get_db),
) -> ResearchRunResponse:
    """Persist a new research run in the local database."""

    run = ResearchRun(question=payload.question)
    db.add(run)
    db.commit()
    db.refresh(run)

    return _serialize_run(run)


@router.get("/runs/{run_id}/documents", response_model=RunDocumentsResponse)
def get_run_documents(run_id: str, db: Session = Depends(get_db)) -> RunDocumentsResponse:
    """Return persisted candidate papers for a run."""

    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    documents = db.scalars(
        select(Document).where(Document.run_id == run.id).order_by(Document.pubdate.desc(), Document.title.asc())
    ).all()

    return RunDocumentsResponse(
        run_id=run.id,
        question=run.question,
        documents_count=len(documents),
        documents=[_serialize_document(document) for document in documents],
    )


@router.get("/documents/{document_id}", response_model=DocumentRecord)
def get_document(document_id: str, db: Session = Depends(get_db)) -> DocumentRecord:
    """Return a single persisted document by ID."""

    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    return _serialize_document(document)


@router.get("/documents/{document_id}/chunks", response_model=DocumentChunksResponse)
def get_document_chunks(document_id: str, db: Session = Depends(get_db)) -> DocumentChunksResponse:
    """Return persisted chunks for a single document."""

    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    chunks = db.scalars(
        select(Chunk).where(Chunk.document_id == document.id).order_by(Chunk.chunk_index.asc())
    ).all()

    return DocumentChunksResponse(
        document_id=document.id,
        run_id=document.run_id,
        chunks_count=len(chunks),
        chunks=[_serialize_chunk(chunk) for chunk in chunks],
    )


@router.get("/chunks/{chunk_id}/claim", response_model=ExtractedClaim)
def get_chunk_claim(chunk_id: str, db: Session = Depends(get_db)) -> ExtractedClaim:
    """Return the saved claim for a single chunk."""

    chunk = db.get(Chunk, chunk_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail="Chunk not found")

    claim = db.scalars(select(Claim).where(Claim.chunk_id == chunk.id)).first()
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")

    return _serialize_claim(claim)


@router.post("/runs/{run_id}/search", response_model=RunSearchResponse)
def search_run_documents(run_id: str, db: Session = Depends(get_db)) -> RunSearchResponse:
    """Search PubMed using the run question and persist candidate papers."""

    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    search_results = search_pubmed(run.question, max_results=10)
    existing_by_pmid = {
        document.pmid: document
        for document in db.scalars(select(Document).where(Document.run_id == run.id)).all()
        if document.pmid
    }

    saved_documents: list[Document] = []
    for result in search_results:
        pmid = result.get("pmid")
        if not pmid:
            continue

        document = existing_by_pmid.get(pmid)
        if document is None:
            document = Document(
                run_id=run.id,
                pmid=pmid,
                title=result.get("title") or "Untitled article",
                journal=result.get("journal"),
                pubdate=result.get("pubdate"),
                authors=result.get("authors"),
                source="pubmed",
                source_url=result.get("source_url"),
            )
            db.add(document)
            existing_by_pmid[pmid] = document
        else:
            document.title = result.get("title") or document.title
            document.journal = result.get("journal")
            document.pubdate = result.get("pubdate")
            document.authors = result.get("authors")
            document.source_url = result.get("source_url")

        saved_documents.append(document)

    if saved_documents:
        run.status = "searched"

    db.commit()

    for document in saved_documents:
        db.refresh(document)
    db.refresh(run)

    return RunSearchResponse(
        run_id=run.id,
        question=run.question,
        documents_found=len(saved_documents),
        documents=[_serialize_document(document) for document in saved_documents],
    )


@router.post("/runs/{run_id}/fetch-abstracts", response_model=AbstractFetchResponse)
def fetch_run_abstracts(run_id: str, db: Session = Depends(get_db)) -> AbstractFetchResponse:
    """Fetch and persist PubMed abstracts for saved documents in a run."""

    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    documents = db.scalars(select(Document).where(Document.run_id == run.id).order_by(Document.title.asc())).all()
    documents_needing_abstracts = [
        document for document in documents if document.pmid and not (document.abstract and document.abstract.strip())
    ]

    abstract_records = fetch_pubmed_abstracts([document.pmid for document in documents_needing_abstracts if document.pmid])
    abstract_by_pmid = {record["pmid"]: record.get("abstract") for record in abstract_records if record.get("pmid")}

    updated_count = 0
    for document in documents_needing_abstracts:
        abstract_text = abstract_by_pmid.get(document.pmid)
        if abstract_text:
            document.abstract = abstract_text
            updated_count += 1

    if updated_count > 0:
        run.status = "enriched"

    db.commit()
    db.refresh(run)

    missing_abstract_count = sum(1 for document in documents if not (document.abstract and document.abstract.strip()))

    return AbstractFetchResponse(
        run_id=run.id,
        documents_total=len(documents),
        documents_updated=updated_count,
        missing_abstract_count=missing_abstract_count,
        status=run.status,
    )


@router.post("/runs/{run_id}/chunk-abstracts", response_model=ChunkingResponse)
def chunk_run_abstracts(run_id: str, db: Session = Depends(get_db)) -> ChunkingResponse:
    """Create chunk rows from saved document abstracts for a run."""

    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    documents = db.scalars(select(Document).where(Document.run_id == run.id).order_by(Document.title.asc())).all()
    documents_with_abstracts = [
        document for document in documents if document.abstract and document.abstract.strip()
    ]

    existing_chunk_document_ids = {
        document_id
        for document_id in db.scalars(select(Chunk.document_id).where(Chunk.run_id == run.id)).all()
    }

    chunked_documents = 0
    chunks_created = 0

    for document in documents_with_abstracts:
        if document.id in existing_chunk_document_ids:
            continue

        chunk_payloads = chunk_document_abstract(document)
        if not chunk_payloads:
            continue

        for payload in chunk_payloads:
            db.add(
                Chunk(
                    run_id=run.id,
                    document_id=document.id,
                    chunk_index=int(payload["chunk_index"]),
                    section=str(payload["section"]),
                    text=str(payload["text"]),
                )
            )
            chunks_created += 1

        chunked_documents += 1

    if chunks_created > 0:
        run.status = "chunked"

    db.commit()
    db.refresh(run)

    return ChunkingResponse(
        run_id=run.id,
        documents_with_abstracts=len(documents_with_abstracts),
        documents_chunked=chunked_documents,
        chunks_created=chunks_created,
        status=run.status,
    )


@router.get("/runs/{run_id}/chunks", response_model=RunChunksResponse)
def get_run_chunks(run_id: str, db: Session = Depends(get_db)) -> RunChunksResponse:
    """Return persisted chunks for a research run."""

    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    chunks = db.scalars(
        select(Chunk).where(Chunk.run_id == run.id).order_by(Chunk.document_id.asc(), Chunk.chunk_index.asc())
    ).all()

    return RunChunksResponse(
        run_id=run.id,
        chunks_count=len(chunks),
        chunks=[_serialize_chunk(chunk, run.question) for chunk in chunks],
    )


@router.post("/runs/{run_id}/rank-chunks", response_model=RankedChunksResponse)
def rank_run_chunks(run_id: str, db: Session = Depends(get_db)) -> RankedChunksResponse:
    """Score all chunks for a run against the research question."""

    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    chunks = db.scalars(
        select(Chunk).where(Chunk.run_id == run.id).order_by(Chunk.document_id.asc(), Chunk.chunk_index.asc())
    ).all()
    if not chunks:
        return RankedChunksResponse(
            run_id=run.id,
            question=run.question,
            chunks_total=0,
            chunks_ranked=0,
            top_chunks=[],
        )

    ranked_chunks = rank_chunks_for_run(run.question, chunks)
    for chunk, score in ranked_chunks:
        chunk.retrieval_score = score

    run.status = "ranked"
    db.commit()
    db.refresh(run)

    top_chunks = [chunk for chunk, _score in ranked_chunks[:10]]
    return RankedChunksResponse(
        run_id=run.id,
        question=run.question,
        chunks_total=len(chunks),
        chunks_ranked=len(ranked_chunks),
        top_chunks=[_serialize_chunk(chunk, run.question) for chunk in top_chunks],
    )


@router.get("/runs/{run_id}/top-chunks", response_model=TopChunksResponse)
def get_top_chunks(
    run_id: str,
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> TopChunksResponse:
    """Return top-ranked chunks for a research run."""

    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    chunks = db.scalars(
        select(Chunk)
        .where(Chunk.run_id == run.id)
        .order_by(desc(Chunk.retrieval_score), Chunk.document_id.asc(), Chunk.chunk_index.asc())
        .limit(limit)
    ).all()

    return TopChunksResponse(
        run_id=run.id,
        question=run.question,
        limit=limit,
        chunks_count=len(chunks),
        chunks=[_serialize_chunk(chunk, run.question) for chunk in chunks],
    )


@router.post("/runs/{run_id}/extract-claims", response_model=ClaimsExtractionResponse)
def extract_run_claims(run_id: str, db: Session = Depends(get_db)) -> ClaimsExtractionResponse:
    """Extract one structured claim from each top-ranked unclaimed chunk."""

    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    ranked_chunks = db.scalars(
        select(Chunk)
        .where(Chunk.run_id == run.id)
        .order_by(desc(Chunk.retrieval_score), Chunk.document_id.asc(), Chunk.chunk_index.asc())
    ).all()
    if not ranked_chunks:
        return ClaimsExtractionResponse(
            run_id=run.id,
            question=run.question,
            chunks_considered=0,
            claims_created=0,
            claims=[],
            errors=[],
        )

    claimed_chunk_ids = {
        chunk_id for chunk_id in db.scalars(select(Claim.chunk_id).where(Claim.run_id == run.id)).all()
    }
    candidate_chunks = [chunk for chunk in ranked_chunks if chunk.id not in claimed_chunk_ids][:5]
    if not candidate_chunks:
        return ClaimsExtractionResponse(
            run_id=run.id,
            question=run.question,
            chunks_considered=0,
            claims_created=0,
            claims=[],
            errors=[],
        )

    extraction_result = extract_claims_for_run(run, candidate_chunks, limit=5)
    claim_payloads = extraction_result["claims"]
    errors = extraction_result["errors"]
    created_claims: list[Claim] = []

    for payload in claim_payloads:
        claim = Claim(**payload)
        db.add(claim)
        created_claims.append(claim)

    if created_claims:
        run.status = "claims_extracted"

    db.commit()

    for claim in created_claims:
        db.refresh(claim)
    db.refresh(run)

    return ClaimsExtractionResponse(
        run_id=run.id,
        question=run.question,
        chunks_considered=len(candidate_chunks),
        claims_created=len(created_claims),
        claims=[_serialize_claim(claim) for claim in created_claims],
        errors=errors,
    )


@router.get("/runs/{run_id}/claims", response_model=RunClaimsResponse)
def get_run_claims(run_id: str, db: Session = Depends(get_db)) -> RunClaimsResponse:
    """Return persisted claims for a research run."""

    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    claims = db.scalars(
        select(Claim)
        .where(Claim.run_id == run.id)
        .order_by(desc(Chunk.retrieval_score), Chunk.chunk_index.asc(), Claim.id.asc())
        .join(Chunk, Claim.chunk_id == Chunk.id)
    ).all()

    return RunClaimsResponse(
        run_id=run.id,
        question=run.question,
        claims_count=len(claims),
        claims=[_serialize_claim(claim) for claim in claims],
    )


@router.post("/runs/{run_id}/evaluate-claims", response_model=ClaimsEvaluationResponse)
def evaluate_run_claims(
    run_id: str,
    force: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> ClaimsEvaluationResponse:
    """Evaluate persisted claims for a research run and save results."""

    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    claims = db.scalars(
        select(Claim)
        .where(Claim.run_id == run.id)
        .order_by(desc(Chunk.retrieval_score), Chunk.chunk_index.asc(), Claim.id.asc())
        .join(Chunk, Claim.chunk_id == Chunk.id)
    ).all()
    if not claims:
        summary = build_run_evaluation_summary([])
        return ClaimsEvaluationResponse(
            run_id=run.id,
            claims_total=0,
            claims_evaluated=0,
            average_overall_score=None,
            verdict_counts={},
            evaluation_summary=ClaimEvaluationSummary(**summary),
            errors=[],
        )

    evaluations, errors = evaluate_claims_for_run(run, claims, force=force)
    db.commit()
    for claim in claims:
        db.refresh(claim)

    summary = build_run_evaluation_summary(claims)
    return ClaimsEvaluationResponse(
        run_id=run.id,
        claims_total=len(claims),
        claims_evaluated=len(evaluations),
        average_overall_score=summary["average_overall_score"],
        verdict_counts=summary["verdict_counts"],
        evaluation_summary=ClaimEvaluationSummary(**summary),
        errors=errors,
    )


@router.get("/runs/{run_id}/evaluations", response_model=RunClaimEvaluationsResponse)
def get_run_evaluations(run_id: str, db: Session = Depends(get_db)) -> RunClaimEvaluationsResponse:
    """Return persisted claim evaluations for a research run."""

    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    claims = db.scalars(
        select(Claim)
        .where(Claim.run_id == run.id)
        .order_by(Claim.evaluation_overall_score.asc().nullslast(), desc(Chunk.retrieval_score), Claim.id.asc())
        .join(Chunk, Claim.chunk_id == Chunk.id)
    ).all()
    evaluated_claims = [claim for claim in claims if claim.evaluation_json]
    summary = build_run_evaluation_summary(claims)

    return RunClaimEvaluationsResponse(
        run_id=run.id,
        question=run.question,
        evaluation_summary=ClaimEvaluationSummary(**summary),
        claims=[_serialize_claim(claim) for claim in evaluated_claims],
    )


@router.post("/runs/{run_id}/generate-brief", response_model=BriefGenerationResponse)
def generate_run_brief(run_id: str, db: Session = Depends(get_db)) -> BriefGenerationResponse:
    """Generate and persist a grounded evidence brief from saved claims."""

    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    claims = db.scalars(
        select(Claim)
        .where(Claim.run_id == run.id)
        .order_by(desc(Chunk.retrieval_score), Claim.document_id.asc())
        .join(Chunk, Claim.chunk_id == Chunk.id)
    ).all()
    if not claims:
        return BriefGenerationResponse(
            run_id=run.id,
            question=run.question,
            brief_generated=False,
            brief=None,
        )

    try:
        brief_payload = generate_brief_for_run(run, claims)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=build_brief_generation_error_summary(exc)) from exc
    evidence_rows = build_evidence_table_for_run(claims)
    run.status = "brief_generated"
    markdown_report = build_markdown_report_for_run(run, brief_payload, claims, evidence_rows)
    existing_brief = db.scalars(select(Brief).where(Brief.run_id == run.id)).first()
    if existing_brief is None:
        existing_brief = Brief(run_id=run.id)
        db.add(existing_brief)

    existing_brief.direct_answer = brief_payload["direct_answer"]
    existing_brief.summary = brief_payload["summary"]
    existing_brief.supporting_findings = json.dumps(brief_payload["supporting_findings"], ensure_ascii=True)
    existing_brief.conflicting_findings = json.dumps(brief_payload["conflicting_findings"], ensure_ascii=True)
    existing_brief.caveats = json.dumps(brief_payload["caveats"], ensure_ascii=True)
    existing_brief.evidence_table_json = json.dumps(evidence_rows, ensure_ascii=True)
    existing_brief.markdown_report = markdown_report

    db.commit()
    db.refresh(existing_brief)
    db.refresh(run)

    return BriefGenerationResponse(
        run_id=run.id,
        question=run.question,
        brief_generated=True,
        brief=_serialize_brief(existing_brief),
    )


@router.get("/runs/{run_id}/brief", response_model=EvidenceBrief)
def get_run_brief(run_id: str, db: Session = Depends(get_db)) -> EvidenceBrief:
    """Return the persisted brief for a research run."""

    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    brief = db.scalars(select(Brief).where(Brief.run_id == run.id)).first()
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")

    return _serialize_brief(brief)


@router.get("/runs/{run_id}/evidence-table", response_model=EvidenceTableResponse)
def get_run_evidence_table(run_id: str, db: Session = Depends(get_db)) -> EvidenceTableResponse:
    """Return the persisted evidence table for a research run."""

    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    brief = db.scalars(select(Brief).where(Brief.run_id == run.id)).first()
    if brief is None or not brief.evidence_table_json:
        raise HTTPException(status_code=404, detail="Evidence table not found")

    return EvidenceTableResponse(
        run_id=run.id,
        question=run.question,
        rows=_deserialize_evidence_rows(brief.evidence_table_json),
    )


@router.get("/runs/{run_id}/report", response_model=MarkdownReportResponse)
def get_run_report(run_id: str, db: Session = Depends(get_db)) -> MarkdownReportResponse:
    """Return the persisted markdown report for a research run."""

    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    brief = db.scalars(select(Brief).where(Brief.run_id == run.id)).first()
    if brief is None or not brief.markdown_report:
        raise HTTPException(status_code=404, detail="Markdown report not found")

    return MarkdownReportResponse(
        run_id=run.id,
        question=run.question,
        markdown_report=brief.markdown_report,
    )


@router.post("/runs/{run_id}/run-pipeline", response_model=PipelineRunResponse)
def run_pipeline(run_id: str, db: Session = Depends(get_db)) -> PipelineRunResponse:
    """Run the existing pipeline stages synchronously for a saved run."""

    try:
        summary = run_pipeline_for_run(run_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return PipelineRunResponse(**summary)


@router.get("/runs/{run_id}/diagnostics", response_model=RunDiagnosticsResponse)
def get_run_diagnostics(run_id: str, db: Session = Depends(get_db)) -> RunDiagnosticsResponse:
    """Return compact diagnostics for a saved research run."""

    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    return RunDiagnosticsResponse(**build_run_diagnostics(run, db))


@router.get("/runs/{run_id}/pipeline-debug", response_model=PipelineDebugResponse)
def get_run_pipeline_debug(run_id: str, db: Session = Depends(get_db)) -> PipelineDebugResponse:
    """Return the latest persisted pipeline debug snapshot for a run."""

    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    return PipelineDebugResponse(**build_pipeline_debug_payload(run))
