"""LLM-backed synthesis of grounded evidence briefs from persisted claims."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from openai import OpenAI

from app.config import get_settings
from app.prompts.brief_synthesis import BRIEF_SYNTHESIS_SYSTEM_PROMPT, build_brief_synthesis_prompt
from app.services.error_utils import normalize_llm_error_message

if TYPE_CHECKING:
    from app.db.models import Claim, ResearchRun

settings = get_settings()


@lru_cache(maxsize=1)
def _get_zai_client() -> OpenAI:
    """Return a cached Z.AI client using the OpenAI SDK."""

    if not settings.z_ai_api_key:
        raise RuntimeError("ZAI_API_KEY is not configured")
    return OpenAI(api_key=settings.z_ai_api_key, base_url=settings.z_ai_base_url)


def generate_brief_for_run(run: ResearchRun, claims: list[Claim]) -> dict[str, Any]:
    """Generate a grounded evidence brief from persisted claims only."""

    prioritized_claims = sorted(
        claims,
        key=lambda claim: (
            1 if claim.claim_repair_note else 0,
            -(claim.chunk.retrieval_score or 0.0) if claim.chunk else 0.0,
            claim.id,
        ),
    )
    normalized_claims = [_claim_to_prompt_payload(claim) for claim in prioritized_claims]
    prompt = build_brief_synthesis_prompt(run.question, normalized_claims)

    client = _get_zai_client()
    response = client.chat.completions.create(
        model=settings.z_ai_model,
        temperature=0.1,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": BRIEF_SYNTHESIS_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    content = response.choices[0].message.content or "{}"
    payload = _parse_json_payload(content)

    return _normalize_brief_payload(payload)


def build_evidence_table_for_run(claims: list[Claim]) -> list[dict[str, Any]]:
    """Build a normalized evidence table from persisted claims."""

    sorted_claims = sorted(
        claims,
        key=lambda claim: (
            -(claim.chunk.retrieval_score or 0.0) if claim.chunk else 0.0,
            claim.chunk.chunk_index if claim.chunk else 0,
            claim.id,
        ),
    )
    return [_claim_to_evidence_row(claim) for claim in sorted_claims]


def build_markdown_report_for_run(
    run: ResearchRun,
    brief: dict[str, Any],
    claims: list[Claim],
    evidence_table_rows: list[dict[str, Any]],
) -> str:
    """Build a deterministic markdown report from persisted run artifacts."""

    lines = [
        f"# OpenBioSignal Report: {run.question}",
        "",
        "## Run Metadata",
        f"- Run ID: `{run.id}`",
        f"- Status: `{run.status}`",
        f"- Claims included: {len(claims)}",
        "",
        "## Direct Answer",
        brief.get("direct_answer", ""),
        "",
        "## Summary",
        brief.get("summary", ""),
        "",
        "## Supporting Findings",
    ]
    lines.extend(_markdown_bullets(brief.get("supporting_findings", [])))
    lines.extend(
        [
            "",
            "## Conflicting Findings",
        ]
    )
    lines.extend(_markdown_bullets(brief.get("conflicting_findings", [])))
    lines.extend(
        [
            "",
            "## Caveats",
        ]
    )
    lines.extend(_markdown_bullets(brief.get("caveats", [])))
    lines.extend(
        [
            "",
            "## Evidence Table",
            "| Document | Stance | Relevance | Outcome | Claim | Evidence Span | Score |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )

    for row in evidence_table_rows:
        lines.append(
            "| {document} | {stance} | {relevance} | {outcome} | {claim_text} | {evidence_span} | {score} |".format(
                document=_escape_markdown_cell(row.get("document_title") or "Untitled document"),
                stance=_escape_markdown_cell(row.get("stance") or "background"),
                relevance=_escape_markdown_cell(row.get("relevance") or "low"),
                outcome=_escape_markdown_cell(row.get("outcome") or "N/A"),
                claim_text=_escape_markdown_cell(row.get("claim_text") or ""),
                evidence_span=_escape_markdown_cell(row.get("evidence_span") or "N/A"),
                score=f"{(row.get('retrieval_score') or 0):.4f}",
            )
        )

    return "\n".join(lines).strip() + "\n"


def _claim_to_prompt_payload(claim: Claim) -> dict[str, Any]:
    """Convert a persisted claim into a synthesis-ready dictionary."""

    return {
        "document_title": claim.document.title if claim.document else None,
        "claim_text": claim.claim_text,
        "stance": claim.stance,
        "relevance": claim.relevance,
        "study_type": claim.study_type,
        "population": claim.population,
        "intervention_or_exposure": claim.intervention_or_exposure,
        "comparator": claim.comparator,
        "outcome": claim.outcome,
        "direction_of_effect": claim.direction_of_effect,
        "limitations": claim.limitations,
        "uncertainty_note": claim.uncertainty_note,
        "evidence_span": claim.evidence_span,
        "retrieval_score": claim.chunk.retrieval_score if claim.chunk else None,
        "claim_repair_note": claim.claim_repair_note,
    }


def _claim_to_evidence_row(claim: Claim) -> dict[str, Any]:
    """Convert a persisted claim into a normalized evidence-table row."""

    document = claim.document
    chunk = claim.chunk
    return {
        "claim_id": claim.id,
        "document_id": claim.document_id,
        "chunk_id": claim.chunk_id,
        "document_title": document.title if document else None,
        "pmid": document.pmid if document else None,
        "stance": claim.stance,
        "relevance": claim.relevance,
        "study_type": claim.study_type,
        "population": claim.population,
        "intervention_or_exposure": claim.intervention_or_exposure,
        "comparator": claim.comparator,
        "outcome": claim.outcome,
        "direction_of_effect": claim.direction_of_effect,
        "limitations": _normalize_string_list(claim.limitations),
        "uncertainty_note": claim.uncertainty_note,
        "evidence_span": claim.evidence_span,
        "claim_text": claim.claim_text,
        "retrieval_score": chunk.retrieval_score if chunk else None,
    }


def _parse_json_payload(content: str) -> dict[str, Any]:
    """Parse a JSON response and tolerate fenced output."""

    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()

    payload = json.loads(cleaned)
    if not isinstance(payload, dict):
        raise ValueError("Model response was not a JSON object")

    return payload


def _normalize_brief_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize model output into the stored brief shape."""

    return {
        "direct_answer": _string_or_fallback(
            payload.get("direct_answer"),
            "Insufficient evidence to provide a grounded direct answer from the extracted claims.",
        ),
        "summary": _string_or_fallback(
            payload.get("summary"),
            "The extracted claims do not yet support a reliable grounded synthesis.",
        ),
        "supporting_findings": _normalize_string_list(payload.get("supporting_findings")),
        "conflicting_findings": _normalize_string_list(payload.get("conflicting_findings")),
        "caveats": _normalize_string_list(payload.get("caveats")),
    }


def _fallback_brief() -> dict[str, Any]:
    """Return a safe fallback brief if synthesis fails."""

    return {
        "direct_answer": "A grounded brief could not be generated from the current claims.",
        "summary": "Brief generation failed or returned malformed output, so no evidence synthesis is available yet.",
        "supporting_findings": [],
        "conflicting_findings": [],
        "caveats": ["Brief generation needs a valid model response."],
    }


def build_brief_generation_error_summary(error: Exception | str) -> str:
    """Return a concise user-facing brief generation error message."""

    return normalize_llm_error_message(error)


def _normalize_string_list(value: Any) -> list[str]:
    """Normalize a model field to a list of non-empty strings."""

    if isinstance(value, list):
        return [item.strip() for item in map(str, value) if str(item).strip()]

    if value is None:
        return []

    text = str(value).strip()
    return [text] if text else []


def _string_or_fallback(value: Any, fallback: str) -> str:
    """Normalize a scalar value to string with a fallback."""

    if value is None:
        return fallback

    text = str(value).strip()
    return text or fallback


def _markdown_bullets(items: list[str]) -> list[str]:
    """Render a list of strings as markdown bullets with a fallback."""

    cleaned_items = [item.strip() for item in items if item and item.strip()]
    if not cleaned_items:
        return ["- None noted."]

    return [f"- {item}" for item in cleaned_items]


def _escape_markdown_cell(value: str) -> str:
    """Keep markdown table cells readable and single-line."""

    return value.replace("\n", " ").replace("|", "\\|").strip()
