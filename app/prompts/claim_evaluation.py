from __future__ import annotations

from typing import Any

CLAIM_EVALUATION_SYSTEM_PROMPT = """You evaluate one extracted biomedical evidence claim using only the supplied materials.
Be strict but fair.
Do not use outside knowledge.
Judge only the research question, claim text, stance, evidence span, rationale, document title, and retrieval score if provided.

Scoring guidance:
- relevance_score: how well the claim addresses the research question
- faithfulness_score: how well the claim appears supported by the evidence span
- stance_fit_score: whether the stance label seems appropriate given the claim and evidence span
- specificity_score: whether the claim is concrete and decision-useful rather than vague
- overall_score: overall usefulness and quality of the claim

Verdict guidance:
- strong: clearly relevant, faithful, and useful
- acceptable: usable but imperfect
- weak: vague, poorly supported, poorly labeled, or not very useful

Return valid JSON only with these keys:
relevance_score, faithfulness_score, stance_fit_score, specificity_score, overall_score, strengths, weaknesses, verdict
"""


def build_claim_evaluation_prompt(research_question: str, claim_payload: dict[str, Any]) -> str:
    """Build the user prompt for a single persisted-claim evaluation call."""

    return (
        f"Research question: {research_question}\n"
        f"Document title: {claim_payload.get('document_title') or 'Unknown'}\n"
        f"Claim text: {claim_payload.get('claim_text') or ''}\n"
        f"Stance: {claim_payload.get('stance') or 'Unknown'}\n"
        f"Evidence span: {claim_payload.get('evidence_span') or ''}\n"
        f"Rationale: {claim_payload.get('rationale') or ''}\n"
        f"Retrieval score: {claim_payload.get('retrieval_score') if claim_payload.get('retrieval_score') is not None else 'Unknown'}\n\n"
        "Instructions:\n"
        "- Score the claim using only the supplied materials.\n"
        "- Be conservative about faithfulness and stance fit.\n"
        "- Keep strengths and weaknesses short and practical.\n"
        "- Return JSON only.\n"
    )
