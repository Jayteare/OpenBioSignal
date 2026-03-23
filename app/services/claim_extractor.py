"""LLM-backed claim extraction for top-ranked chunks."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import TYPE_CHECKING, Any
import re

from openai import OpenAI

from app.config import get_settings
from app.services.error_utils import normalize_llm_error_message
from app.prompts.claim_extraction import CLAIM_EXTRACTION_SYSTEM_PROMPT, build_claim_extraction_prompt

if TYPE_CHECKING:
    from app.db.models import Chunk, Document, ResearchRun

settings = get_settings()
ALLOWED_STANCES = {"supports", "weakens", "mixed", "background"}
ALLOWED_RELEVANCE = {"high", "medium", "low"}
RESULT_LIKE_TERMS = (
    "result",
    "results",
    "conclusion",
    "conclusions",
    "found",
    "observed",
    "improved",
    "reduced",
    "associated",
    "significant",
    "compared with",
    "placebo",
    "effect",
    "increase",
    "decrease",
    "benefit",
    "no significant difference",
)
RESULT_LIKE_SECTION_TERMS = ("result", "results", "conclusion", "conclusions", "finding", "discussion")
NUMERIC_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\b")
DOSAGE_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\s*(?:iu/day|iu|mg/day|mg|g/day|g|mcg/day|mcg)\b")
COMPARATIVE_MARKERS = ("more than", "less than", "higher than", "lower than", ">=", "<=", "compared with")
CERTAINTY_MARKERS = ("strong evidence", "moderate evidence", "high certainty", "low certainty", "likely", "probably")
SUBGROUP_MARKERS = ("subgroup", "among", "in patients with", "in participants with", "stratified")
STATISTICAL_MARKERS = ("ci", "confidence interval", "p <", "p<", "or ", "rr ", "smd")


@lru_cache(maxsize=1)
def _get_zai_client() -> OpenAI:
    """Return a cached Z.AI client using the OpenAI SDK."""

    if not settings.z_ai_api_key:
        raise RuntimeError("ZAI_API_KEY is not configured")
    return OpenAI(api_key=settings.z_ai_api_key, base_url=settings.z_ai_base_url)


def extract_claim_from_chunk(run_question: str, document: Document, chunk: Chunk) -> dict[str, Any]:
    """Extract one normalized structured claim from a ranked chunk."""

    client = _get_zai_client()
    prompt = build_claim_extraction_prompt(
        research_question=run_question,
        title=document.title,
        year=document.pubdate,
        journal=document.journal,
        section=chunk.section,
        pmid=document.pmid,
        chunk_text=chunk.text,
    )

    response = client.chat.completions.create(
        model=settings.z_ai_model,
        temperature=0.1,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": CLAIM_EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    content = response.choices[0].message.content or "{}"
    payload = _parse_json_payload(content)
    return _normalize_claim_payload(payload=payload, document=document, chunk=chunk)


def extract_claims_for_run(
    run: ResearchRun,
    ranked_chunks: list[Chunk],
    limit: int = 5,
) -> dict[str, Any]:
    """Extract claims for the top-ranked chunks in a run."""

    claims: list[dict[str, Any]] = []
    errors: list[str] = []
    failures: list[dict[str, str]] = []
    considered_chunks = ranked_chunks[:limit]
    stance_counts = {stance: 0 for stance in ALLOWED_STANCES}
    stance_adjustments_applied = 0

    for chunk in considered_chunks:
        if chunk.document is None:
            message = "missing document context"
            errors.append(f"Chunk {chunk.id}: {message}")
            failures.append(
                {
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "document_title": "Unknown document",
                    "error": message,
                }
            )
            continue

        try:
            claim_payload = extract_claim_from_chunk(run.question, chunk.document, chunk)
            claims.append(claim_payload)
            normalized_stance = str(claim_payload.get("stance") or "background")
            stance_counts[normalized_stance] = stance_counts.get(normalized_stance, 0) + 1
            if claim_payload.get("stance_adjustment_note"):
                stance_adjustments_applied += 1
        except Exception as exc:  # noqa: BLE001
            message = _summarize_claim_extraction_error(exc)
            errors.append(f"Chunk {chunk.id}: {message}")
            failures.append(
                {
                    "chunk_id": chunk.id,
                    "document_id": chunk.document.id,
                    "document_title": chunk.document.title or "Untitled document",
                    "error": message,
                    "raw_error": str(exc).strip()[:300],
                }
            )

    return {
        "claims": claims,
        "errors": errors,
        "debug": {
            "chunk_ids_considered": [chunk.id for chunk in considered_chunks],
            "extraction_attempts": len(considered_chunks),
            "extraction_failures": len(failures),
            "background_claims_created": stance_counts.get("background", 0),
            "supports_claims_created": stance_counts.get("supports", 0),
            "weakens_claims_created": stance_counts.get("weakens", 0),
            "mixed_claims_created": stance_counts.get("mixed", 0),
            "stance_adjustments_applied": stance_adjustments_applied,
            "failure_details": failures,
        },
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


def _normalize_claim_payload(payload: dict[str, Any], document: Document, chunk: Chunk) -> dict[str, Any]:
    """Normalize LLM output into a conservative stored claim shape."""

    claim_text = _string_or_none(payload.get("claim_text"))
    if not claim_text:
        raise ValueError("Missing claim_text in model response")

    evidence_span = _normalize_evidence_span(_string_or_none(payload.get("evidence_span")), chunk.text)
    limitations = payload.get("limitations")
    if isinstance(limitations, (list, dict)):
        limitations_text = json.dumps(limitations, ensure_ascii=True)
    else:
        limitations_text = _string_or_none(limitations)

    stance = _string_or_none(payload.get("stance")) or "background"
    relevance = _string_or_none(payload.get("relevance")) or "low"
    rationale = _string_or_none(payload.get("rationale"))
    normalized_stance = stance if stance in ALLOWED_STANCES else "background"
    stance_adjustment_note = None
    claim_repair_note = None

    if normalized_stance == "background" and looks_like_result_chunk(chunk.text, chunk.section):
        normalized_stance = "mixed"
        stance_adjustment_note = "model_plus_heuristic_result_like_chunk"
        rationale = _append_rationale_note(
            rationale,
            "Stance adjusted from background to mixed because the chunk contains result-like or conclusion-like language.",
        )

    overreach_signals = claim_overreach_signals(claim_text, evidence_span)
    if overreach_signals:
        claim_text = _repair_claim_text_for_span_faithfulness(claim_text, evidence_span)
        claim_repair_note = f"repaired_for_span_faithfulness:{','.join(overreach_signals)}"
        rationale = _append_rationale_note(
            rationale,
            "Claim text was tightened to stay closer to the selected evidence span.",
        )

    return {
        "run_id": chunk.run_id,
        "document_id": document.id,
        "chunk_id": chunk.id,
        "claim_text": claim_text,
        "stance": normalized_stance,
        "relevance": relevance if relevance in ALLOWED_RELEVANCE else "low",
        "study_type": _string_or_none(payload.get("study_type")),
        "population": _string_or_none(payload.get("population")),
        "intervention_or_exposure": _string_or_none(payload.get("intervention_or_exposure")),
        "comparator": _string_or_none(payload.get("comparator")),
        "outcome": _string_or_none(payload.get("outcome")),
        "direction_of_effect": _string_or_none(payload.get("direction_of_effect")),
        "limitations": limitations_text,
        "uncertainty_note": _string_or_none(payload.get("uncertainty_note")),
        "evidence_span": evidence_span,
        "rationale": rationale,
        "stance_adjustment_note": stance_adjustment_note,
        "claim_repair_note": claim_repair_note,
    }


def looks_like_result_chunk(chunk_text: str, section: str | None = None) -> bool:
    """Return True when a chunk likely contains findings or conclusions."""

    normalized_text = chunk_text.lower()
    normalized_section = (section or "").lower()

    if any(term in normalized_section for term in RESULT_LIKE_SECTION_TERMS):
        return True

    matched_terms = sum(1 for term in RESULT_LIKE_TERMS if term in normalized_text)
    return matched_terms >= 2


def claim_overreach_signals(claim_text: str, evidence_span: str) -> list[str]:
    """Return short deterministic signals for likely claim details unsupported by the evidence span."""

    signals: list[str] = []
    normalized_claim = claim_text.lower()
    normalized_span = evidence_span.lower()

    claim_numbers = set(NUMERIC_PATTERN.findall(normalized_claim))
    span_numbers = set(NUMERIC_PATTERN.findall(normalized_span))
    if claim_numbers - span_numbers:
        signals.append("numeric_detail_not_in_span")

    if _contains_pattern_without_support(DOSAGE_PATTERN, normalized_claim, normalized_span):
        signals.append("dosage_detail_not_in_span")
    if _contains_marker_without_support(COMPARATIVE_MARKERS, normalized_claim, normalized_span):
        signals.append("comparative_detail_not_in_span")
    if _contains_marker_without_support(CERTAINTY_MARKERS, normalized_claim, normalized_span):
        signals.append("certainty_detail_not_in_span")
    if _contains_marker_without_support(SUBGROUP_MARKERS, normalized_claim, normalized_span):
        signals.append("subgroup_detail_not_in_span")
    if _contains_marker_without_support(STATISTICAL_MARKERS, normalized_claim, normalized_span):
        signals.append("statistical_detail_not_in_span")

    return list(dict.fromkeys(signals))


def _normalize_evidence_span(evidence_span: str | None, chunk_text: str) -> str:
    """Use a passage-bounded evidence span with a simple fallback."""

    if evidence_span and evidence_span in chunk_text:
        return evidence_span

    first_sentence = chunk_text.split(". ")[0].strip()
    if first_sentence:
        return first_sentence[:280]

    return chunk_text[:280].strip()


def _string_or_none(value: Any) -> str | None:
    """Normalize scalar model fields to stripped strings."""

    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _append_rationale_note(rationale: str | None, note: str) -> str:
    """Append a short adjustment note to an existing rationale."""

    if rationale:
        return f"{rationale} {note}"
    return note


def _repair_claim_text_for_span_faithfulness(claim_text: str, evidence_span: str) -> str:
    """Conservatively rewrite claim text to stay closer to the evidence span."""

    repaired = evidence_span.strip().strip('"')
    if not repaired:
        return claim_text

    repaired = re.sub(r"\s+", " ", repaired)
    if len(repaired) > 240:
        repaired = repaired[:237].rstrip(" ,;:") + "..."
    if repaired[-1:] and repaired[-1] not in ".!?":
        repaired += "."
    return repaired


def _contains_pattern_without_support(pattern: re.Pattern[str], claim_text: str, evidence_span: str) -> bool:
    """Return True when a regex pattern appears in the claim but not in the evidence span."""

    return bool(pattern.search(claim_text) and not pattern.search(evidence_span))


def _contains_marker_without_support(markers: tuple[str, ...], claim_text: str, evidence_span: str) -> bool:
    """Return True when any marker appears in the claim but not in the evidence span."""

    return any(marker in claim_text and marker not in evidence_span for marker in markers)


def _summarize_claim_extraction_error(exc: Exception) -> str:
    """Convert extraction exceptions into short render-safe messages."""

    message = str(exc).strip() or exc.__class__.__name__
    lowered = message.lower()

    normalized_message = normalize_llm_error_message(message)
    if normalized_message != " ".join(message.split())[:220]:
        return normalized_message
    if "zai_api_key" in lowered or "api key" in lowered:
        return "missing API key"
    if "json" in lowered:
        return "invalid JSON response"
    if "missing claim_text" in lowered or "model response" in lowered:
        return "invalid model response"
    if "document context" in lowered:
        return "missing document context"
    return message[:180]
