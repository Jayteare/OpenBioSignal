"""In-process orchestration for running the existing pipeline stages."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models import Brief, Chunk, Claim, Document, ResearchRun
from app.services.brief_generator import (
    build_brief_generation_error_summary,
    build_evidence_table_for_run,
    build_markdown_report_for_run,
    generate_brief_for_run,
)
from app.services.chunker import chunk_document_abstract
from app.services.claim_extractor import extract_claims_for_run
from app.services.error_utils import normalize_llm_error_message
from app.services.pipeline_debug import persist_pipeline_debug
from app.services.pubmed_search import fetch_pubmed_abstracts, search_pubmed
from app.services.retriever import rank_chunks_for_run


def run_pipeline_for_run(run_id: str, db: Session) -> dict[str, Any]:
    """Run the existing synchronous pipeline stages for a persisted run."""

    run = db.get(ResearchRun, run_id)
    if run is None:
        raise LookupError("Run not found")

    errors: list[str] = []
    steps: dict[str, dict[str, Any]] = {}

    try:
        steps["search"] = _run_search_stage(run, db)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"search: {exc}")
        steps["search"] = {"documents_found": 0, "documents_total": _count_documents(run.id, db)}

    try:
        steps["fetch_abstracts"] = _run_fetch_abstracts_stage(run, db)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"fetch_abstracts: {exc}")
        steps["fetch_abstracts"] = {
            "documents_updated": 0,
            "abstracts_available": _count_abstracts(run.id, db),
        }

    try:
        steps["chunk_abstracts"] = _run_chunk_abstracts_stage(run, db)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"chunk_abstracts: {exc}")
        steps["chunk_abstracts"] = {
            "documents_chunked": 0,
            "chunks_created": 0,
            "chunks_total": _count_chunks(run.id, db),
        }

    try:
        steps["rank_chunks"] = _run_rank_chunks_stage(run, db)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"rank_chunks: {exc}")
        steps["rank_chunks"] = {
            "chunks_ranked": 0,
            "top_chunk_count": 0,
        }

    try:
        claim_stage_summary, claim_stage_errors = _run_extract_claims_stage(run, db)
        steps["extract_claims"] = claim_stage_summary
        errors.extend(f"extract_claims: {error}" for error in claim_stage_errors)
    except Exception as exc:  # noqa: BLE001
        normalized_error = normalize_llm_error_message(exc)
        errors.append(f"extract_claims: {normalized_error}")
        steps["extract_claims"] = {
            "chunks_considered": 0,
            "chunk_ids_considered": [],
            "chunks_skipped_existing_claim": 0,
            "already_claimed_chunk_ids_skipped": [],
            "claims_created": 0,
            "extraction_attempts": 0,
            "extraction_failures": 1,
            "background_claims_created": 0,
            "supports_claims_created": 0,
            "weakens_claims_created": 0,
            "mixed_claims_created": 0,
            "stance_adjustments_applied": 0,
            "failure_details": [{"error": normalized_error, "raw_error": str(exc)}],
            "claims_total": _count_claims(run.id, db),
        }

    try:
        steps["generate_brief"] = _run_generate_brief_stage(run, db)
    except Exception as exc:  # noqa: BLE001
        normalized_error = build_brief_generation_error_summary(exc)
        errors.append(f"generate_brief: {normalized_error}")
        brief = _get_brief(run.id, db)
        steps["generate_brief"] = {
            "claims_available": _count_claims(run.id, db),
            "brief_generated": bool(brief),
            "evidence_table_rows": _count_evidence_rows(brief),
            "markdown_report_available": bool(brief and brief.markdown_report),
            "error": normalized_error,
            "raw_error": str(exc),
        }

    db.refresh(run)
    brief = _get_brief(run.id, db)

    summary = {
        "run_id": run.id,
        "question": run.question,
        "status": run.status,
        "documents_total": _count_documents(run.id, db),
        "abstracts_available": _count_abstracts(run.id, db),
        "chunks_total": _count_chunks(run.id, db),
        "ranked_chunks": _count_ranked_chunks(run.id, db),
        "claims_total": _count_claims(run.id, db),
        "brief_generated": brief is not None,
        "brief_id": brief.id if brief else None,
        "steps": steps,
        "errors": errors,
    }
    persist_pipeline_debug(run, summary, errors)
    db.commit()
    db.refresh(run)
    return summary


def _run_search_stage(run: ResearchRun, db: Session) -> dict[str, int]:
    """Search PubMed and upsert candidate documents for a run."""

    search_results = search_pubmed(run.question, max_results=10)
    existing_by_pmid = {
        document.pmid: document
        for document in db.scalars(select(Document).where(Document.run_id == run.id)).all()
        if document.pmid
    }

    saved_documents = 0
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

        saved_documents += 1

    if saved_documents:
        run.status = "searched"

    db.commit()
    db.refresh(run)
    return {
        "documents_found": saved_documents,
        "documents_total": _count_documents(run.id, db),
    }


def _run_fetch_abstracts_stage(run: ResearchRun, db: Session) -> dict[str, int]:
    """Fetch missing abstracts for existing documents."""

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

    if updated_count:
        run.status = "enriched"

    db.commit()
    db.refresh(run)
    return {
        "documents_updated": updated_count,
        "abstracts_available": _count_abstracts(run.id, db),
    }


def _run_chunk_abstracts_stage(run: ResearchRun, db: Session) -> dict[str, int]:
    """Create chunks for documents with abstracts, skipping already chunked docs."""

    documents = db.scalars(select(Document).where(Document.run_id == run.id).order_by(Document.title.asc())).all()
    documents_with_abstracts = [
        document for document in documents if document.abstract and document.abstract.strip()
    ]
    existing_chunk_document_ids = {
        document_id for document_id in db.scalars(select(Chunk.document_id).where(Chunk.run_id == run.id)).all()
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

    if chunks_created:
        run.status = "chunked"

    db.commit()
    db.refresh(run)
    return {
        "documents_chunked": chunked_documents,
        "chunks_created": chunks_created,
        "chunks_total": _count_chunks(run.id, db),
    }


def _run_rank_chunks_stage(run: ResearchRun, db: Session) -> dict[str, int]:
    """Score all chunks for a run using lexical relevance."""

    chunks = db.scalars(
        select(Chunk).where(Chunk.run_id == run.id).order_by(Chunk.document_id.asc(), Chunk.chunk_index.asc())
    ).all()
    if not chunks:
        return {"chunks_ranked": 0, "top_chunk_count": 0}

    ranked_chunks = rank_chunks_for_run(run.question, chunks)
    for chunk, score in ranked_chunks:
        chunk.retrieval_score = score

    run.status = "ranked"
    db.commit()
    db.refresh(run)
    return {
        "chunks_ranked": len(ranked_chunks),
        "top_chunk_count": min(len(ranked_chunks), 10),
    }


def _run_extract_claims_stage(run: ResearchRun, db: Session) -> tuple[dict[str, Any], list[str]]:
    """Extract claims for top-ranked chunks that do not yet have a claim."""

    ranked_chunks = db.scalars(
        select(Chunk)
        .where(Chunk.run_id == run.id)
        .order_by(desc(Chunk.retrieval_score), Chunk.document_id.asc(), Chunk.chunk_index.asc())
    ).all()
    if not ranked_chunks:
        return (
            {
                "chunks_considered": 0,
                "chunk_ids_considered": [],
                "chunks_skipped_existing_claim": 0,
                "already_claimed_chunk_ids_skipped": [],
                "claims_created": 0,
                "claims_total": _count_claims(run.id, db),
                "extraction_attempts": 0,
                "extraction_failures": 0,
                "background_claims_created": 0,
                "supports_claims_created": 0,
                "weakens_claims_created": 0,
                "mixed_claims_created": 0,
                "stance_adjustments_applied": 0,
                "failure_details": [],
            },
            [],
        )

    claimed_chunk_ids = {
        chunk_id for chunk_id in db.scalars(select(Claim.chunk_id).where(Claim.run_id == run.id)).all()
    }
    skipped_existing_claim_ids = [chunk.id for chunk in ranked_chunks if chunk.id in claimed_chunk_ids]
    candidate_chunks = [chunk for chunk in ranked_chunks if chunk.id not in claimed_chunk_ids][:5]
    if not candidate_chunks:
        return (
            {
                "chunks_considered": 0,
                "chunk_ids_considered": [],
                "chunks_skipped_existing_claim": len(skipped_existing_claim_ids),
                "already_claimed_chunk_ids_skipped": skipped_existing_claim_ids[:10],
                "claims_created": 0,
                "claims_total": _count_claims(run.id, db),
                "extraction_attempts": 0,
                "extraction_failures": 0,
                "background_claims_created": 0,
                "supports_claims_created": 0,
                "weakens_claims_created": 0,
                "mixed_claims_created": 0,
                "stance_adjustments_applied": 0,
                "failure_details": [],
            },
            [],
        )

    extraction_result = extract_claims_for_run(run, candidate_chunks, limit=5)
    claim_payloads = extraction_result["claims"]
    errors = extraction_result["errors"]
    debug = extraction_result["debug"]
    created_claims = 0
    persistence_failure_details: list[dict[str, str]] = []

    try:
        for payload in claim_payloads:
            db.add(Claim(**payload))
            created_claims += 1

        if created_claims:
            run.status = "claims_extracted"

        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        created_claims = 0
        persistence_failure_details.append({"error": f"DB persistence error: {exc}"})
        errors = [*errors, f"DB persistence error: {exc}"]

    db.refresh(run)
    return (
        {
            "chunks_considered": len(candidate_chunks),
            "chunk_ids_considered": debug["chunk_ids_considered"],
            "chunks_skipped_existing_claim": len(skipped_existing_claim_ids),
            "already_claimed_chunk_ids_skipped": skipped_existing_claim_ids[:10],
            "claims_created": created_claims,
            "claims_total": _count_claims(run.id, db),
            "extraction_attempts": debug["extraction_attempts"],
            "extraction_failures": debug["extraction_failures"] + len(persistence_failure_details),
            "background_claims_created": debug["background_claims_created"],
            "supports_claims_created": debug["supports_claims_created"],
            "weakens_claims_created": debug["weakens_claims_created"],
            "mixed_claims_created": debug["mixed_claims_created"],
            "stance_adjustments_applied": debug["stance_adjustments_applied"],
            "failure_details": [*debug["failure_details"], *persistence_failure_details],
        },
        errors,
    )


def _run_generate_brief_stage(run: ResearchRun, db: Session) -> dict[str, int | bool]:
    """Generate and persist a brief, evidence table, and markdown report."""

    claims = db.scalars(
        select(Claim)
        .where(Claim.run_id == run.id)
        .order_by(desc(Chunk.retrieval_score), Claim.document_id.asc())
        .join(Chunk, Claim.chunk_id == Chunk.id)
    ).all()
    if not claims:
        return {
            "claims_available": 0,
            "brief_generated": False,
            "evidence_table_rows": 0,
            "markdown_report_available": False,
        }

    brief_payload = generate_brief_for_run(run, claims)
    evidence_rows = build_evidence_table_for_run(claims)
    run.status = "brief_generated"
    markdown_report = build_markdown_report_for_run(run, brief_payload, claims, evidence_rows)

    existing_brief = _get_brief(run.id, db)
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
    return {
        "claims_available": len(claims),
        "brief_generated": True,
        "evidence_table_rows": len(evidence_rows),
        "markdown_report_available": bool(existing_brief.markdown_report),
    }


def _get_brief(run_id: str, db: Session) -> Brief | None:
    """Return the current brief for a run, if present."""

    return db.scalars(select(Brief).where(Brief.run_id == run_id)).first()


def _count_documents(run_id: str, db: Session) -> int:
    """Count persisted documents for a run."""

    return len(db.scalars(select(Document.id).where(Document.run_id == run_id)).all())


def _count_abstracts(run_id: str, db: Session) -> int:
    """Count documents with non-empty abstracts for a run."""

    documents = db.scalars(select(Document).where(Document.run_id == run_id)).all()
    return sum(1 for document in documents if document.abstract and document.abstract.strip())


def _count_chunks(run_id: str, db: Session) -> int:
    """Count persisted chunks for a run."""

    return len(db.scalars(select(Chunk.id).where(Chunk.run_id == run_id)).all())


def _count_ranked_chunks(run_id: str, db: Session) -> int:
    """Count chunks with a retrieval score for a run."""

    chunks = db.scalars(select(Chunk).where(Chunk.run_id == run_id)).all()
    return sum(1 for chunk in chunks if chunk.retrieval_score is not None)


def _count_claims(run_id: str, db: Session) -> int:
    """Count persisted claims for a run."""

    return len(db.scalars(select(Claim.id).where(Claim.run_id == run_id)).all())


def _count_evidence_rows(brief: Brief | None) -> int:
    """Count persisted evidence rows on a brief."""

    if brief is None or not brief.evidence_table_json:
        return 0

    try:
        payload = json.loads(brief.evidence_table_json)
    except json.JSONDecodeError:
        payload = []

    return len(payload) if isinstance(payload, list) else 0
