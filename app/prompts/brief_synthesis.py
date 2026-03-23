from __future__ import annotations

import json

BRIEF_SYNTHESIS_SYSTEM_PROMPT = """You synthesize a grounded biomedical evidence brief using only the provided claims.
Do not use outside knowledge.
Do not invent evidence or certainty.
Reflect conflicting findings and caveats when present.
Keep the answer cautious and evidence-bounded.
Return valid JSON only with these keys:
direct_answer, summary, supporting_findings, conflicting_findings, caveats
"""

BRIEF_SYNTHESIS_PROMPT = BRIEF_SYNTHESIS_SYSTEM_PROMPT


def build_brief_synthesis_prompt(research_question: str, claims: list[dict]) -> str:
    """Build the synthesis prompt from persisted structured claims."""

    claims_block = json.dumps(claims, indent=2, ensure_ascii=True)
    return (
        f"Research question: {research_question}\n\n"
        "Structured claims:\n"
        f"{claims_block}\n\n"
        "Instructions:\n"
        "- Use only these claims.\n"
        "- direct_answer should be short, cautious, and explicitly evidence-bounded.\n"
        "- summary should be one concise paragraph.\n"
        "- supporting_findings, conflicting_findings, and caveats must be short lists of strings.\n"
        "- If evidence is sparse or mixed, say so.\n"
        "- Return JSON only.\n"
    )
