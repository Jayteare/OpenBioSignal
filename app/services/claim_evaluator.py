"""LLM-backed evaluation of persisted extracted claims."""

from __future__ import annotations

import json
from functools import lru_cache
from statistics import mean
from typing import TYPE_CHECKING, Any

from openai import OpenAI

from app.config import get_settings
from app.prompts.claim_evaluation import CLAIM_EVALUATION_SYSTEM_PROMPT, build_claim_evaluation_prompt
from app.services.error_utils import normalize_llm_error_message

if TYPE_CHECKING:
    from app.db.models import Claim, ResearchRun

settings = get_settings()
ALLOWED_VERDICTS = {"strong", "acceptable", "weak"}


@lru_cache(maxsize=1)
def _get_zai_client() -> OpenAI:
    """Return a cached Z.AI client using the OpenAI SDK."""

    if not settings.z_ai_api_key:
        raise RuntimeError("ZAI_API_KEY is not configured")
    return OpenAI(api_key=settings.z_ai_api_key, base_url=settings.z_ai_base_url)


def evaluate_claim(run_question: str, claim: Claim) -> dict[str, Any]:
    """Evaluate one persisted claim and return normalized scores and notes."""

    prompt = build_claim_evaluation_prompt(
        run_question,
        {
            "document_title": claim.document.title if claim.document else None,
            "claim_text": claim.claim_text,
            "stance": claim.stance,
            "evidence_span": claim.evidence_span,
            "rationale": claim.rationale,
            "retrieval_score": claim.chunk.retrieval_score if claim.chunk else None,
        },
    )
    client = _get_zai_client()
    response = client.chat.completions.create(
        model=settings.z_ai_model,
        temperature=0.1,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": CLAIM_EVALUATION_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    content = response.choices[0].message.content or "{}"
    payload = _parse_json_payload(content)
    normalized = _normalize_evaluation_payload(payload)
    normalized["claim_id"] = claim.id
    return normalized


def evaluate_claims_for_run(
    run: ResearchRun,
    claims: list[Claim],
    limit: int | None = None,
    force: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Evaluate persisted claims for a run and persist results onto each claim."""

    errors: list[str] = []
    target_claims = [claim for claim in claims if force or not claim.evaluation_json]
    if limit is not None:
        target_claims = target_claims[:limit]

    results: list[dict[str, Any]] = []
    for claim in target_claims:
        try:
            evaluation = evaluate_claim(run.question, claim)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Claim {claim.id}: {normalize_llm_error_message(exc)}")
            continue

        claim.evaluation_json = json.dumps(evaluation, ensure_ascii=True)
        claim.evaluation_overall_score = float(evaluation["overall_score"])
        claim.evaluation_verdict = str(evaluation["verdict"])
        results.append(evaluation)

    return results, errors


def get_claim_evaluation_data(claim: Claim) -> dict[str, Any]:
    """Return normalized persisted evaluation data for one claim."""

    if not claim.evaluation_json:
        return _empty_evaluation_payload()

    try:
        payload = json.loads(claim.evaluation_json)
    except json.JSONDecodeError:
        payload = {}

    if not isinstance(payload, dict):
        payload = {}

    normalized = _normalize_evaluation_payload(payload)
    normalized["overall_score"] = claim.evaluation_overall_score or normalized["overall_score"]
    normalized["verdict"] = claim.evaluation_verdict or normalized["verdict"]
    return normalized


def build_run_evaluation_summary(claims: list[Claim]) -> dict[str, Any]:
    """Build a compact aggregate summary from persisted claim evaluations."""

    evaluations = [get_claim_evaluation_data(claim) for claim in claims if claim.evaluation_json]
    verdict_counts = {"strong": 0, "acceptable": 0, "weak": 0}
    for evaluation in evaluations:
        verdict = str(evaluation["verdict"])
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1

    return {
        "claims_total": len(claims),
        "claims_evaluated": len(evaluations),
        "average_relevance_score": _average_score(evaluations, "relevance_score"),
        "average_faithfulness_score": _average_score(evaluations, "faithfulness_score"),
        "average_stance_fit_score": _average_score(evaluations, "stance_fit_score"),
        "average_specificity_score": _average_score(evaluations, "specificity_score"),
        "average_overall_score": _average_score(evaluations, "overall_score"),
        "verdict_counts": verdict_counts,
        "weak_claim_count": verdict_counts.get("weak", 0),
        "strong_claim_count": verdict_counts.get("strong", 0),
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


def _normalize_evaluation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize evaluator output into a stable persisted structure."""

    verdict = str(payload.get("verdict") or "acceptable").strip().lower()
    if verdict not in ALLOWED_VERDICTS:
        verdict = "acceptable"

    return {
        "relevance_score": _score_1_to_5(payload.get("relevance_score")),
        "faithfulness_score": _score_1_to_5(payload.get("faithfulness_score")),
        "stance_fit_score": _score_1_to_5(payload.get("stance_fit_score")),
        "specificity_score": _score_1_to_5(payload.get("specificity_score")),
        "overall_score": _score_1_to_5(payload.get("overall_score")),
        "strengths": _normalize_string_list(payload.get("strengths")),
        "weaknesses": _normalize_string_list(payload.get("weaknesses")),
        "verdict": verdict,
    }


def _empty_evaluation_payload() -> dict[str, Any]:
    """Return a blank evaluation payload for unevaluated claims."""

    return {
        "relevance_score": None,
        "faithfulness_score": None,
        "stance_fit_score": None,
        "specificity_score": None,
        "overall_score": None,
        "strengths": [],
        "weaknesses": [],
        "verdict": None,
    }


def _score_1_to_5(value: Any) -> float | None:
    """Clamp numeric scores to the 1-5 range."""

    try:
        score = float(value)
    except (TypeError, ValueError):
        return None

    return max(1.0, min(5.0, round(score, 2)))


def _normalize_string_list(value: Any) -> list[str]:
    """Normalize a model field to a list of short strings."""

    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]

    if value is None:
        return []

    text = str(value).strip()
    return [text] if text else []


def _average_score(evaluations: list[dict[str, Any]], key: str) -> float | None:
    """Average a score key across evaluated claims."""

    values = [float(item[key]) for item in evaluations if item.get(key) is not None]
    if not values:
        return None
    return round(mean(values), 2)
