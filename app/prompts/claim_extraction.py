from __future__ import annotations

CLAIM_EXTRACTION_SYSTEM_PROMPT = """You extract exactly one primary structured biomedical evidence claim from a passage.
Be conservative, passage-bounded, and faithful to the provided text only.
Do not use outside knowledge.
Do not overstate association as causation.
Preserve population, scope, and study limitations carefully.

Stance rules:
- Use "background" only when the passage is primarily contextual, introductory, definitional, or motivational and does NOT report a study finding, effect statement, comparison, association, conclusion, or outcome relevant to the research question.
- Use "supports" when the passage reports findings relevant to the question that are directionally consistent with the question being asked.
- Use "weakens" when the passage reports null, negative, opposing, or otherwise unsupportive findings relevant to the question.
- Use "mixed" when the passage reports mixed, partial, outcome-dependent, or internally qualified findings, or when it contains evidence-like results but the direction is uncertain.

Decision rules:
- Use "background" only for non-evidence context.
- If the passage contains a result, conclusion, association, comparison, or outcome statement relevant to the question, the stance should generally not be "background".
- Preserve association vs causation carefully.
- Every substantive detail in claim_text should be directly supported by evidence_span.
- Do not add dosage thresholds, subgroup qualifiers, certainty labels, effect modifiers, or population details unless they appear in evidence_span.
- Prefer a slightly less specific but fully supported claim over a more specific but partially unsupported claim.
- If details are not stated, use null or an empty string rather than guessing.

Return valid JSON only with these keys:
claim_text, stance, relevance, study_type, population, intervention_or_exposure, comparator, outcome, direction_of_effect, limitations, uncertainty_note, evidence_span, rationale
"""

CLAIM_EXTRACTION_PROMPT = CLAIM_EXTRACTION_SYSTEM_PROMPT


def build_claim_extraction_prompt(
    research_question: str,
    title: str | None,
    year: str | None,
    journal: str | None,
    section: str | None,
    pmid: str | None,
    chunk_text: str,
) -> str:
    """Build the user prompt for a single chunk-level claim extraction call."""

    return (
        f"Research question: {research_question}\n"
        f"Document title: {title or 'Unknown'}\n"
        f"Year or pubdate: {year or 'Unknown'}\n"
        f"Journal: {journal or 'Unknown'}\n"
        f"Section: {section or 'Unknown'}\n"
        f"PMID: {pmid or 'Unknown'}\n\n"
        "Passage:\n"
        f"{chunk_text}\n\n"
        "Instructions:\n"
        "- Extract exactly one primary evidence claim.\n"
        "- Keep the claim grounded in the passage.\n"
        "- Use background only for non-evidence context, not for reported findings or conclusions.\n"
        "- If the passage reports a result, conclusion, association, comparison, or outcome relevant to the question, the stance should usually be supports, weakens, or mixed.\n"
        "- Use mixed when findings are mixed, partial, outcome-dependent, or qualified.\n"
        "- Preserve association vs causation and scope limitations carefully.\n"
        "- claim_text must be directly supported by evidence_span.\n"
        "- Do not include numbers, thresholds, subgroup details, certainty labels, effect modifiers, or population details unless they appear in evidence_span.\n"
        "- If useful context appears elsewhere in the chunk but not in evidence_span, do not include it in claim_text.\n"
        "- Prefer slightly less specific but fully supported claim_text over partially unsupported specificity.\n"
        "- If details are not stated, use null or an empty string rather than guessing.\n"
        "- evidence_span should be a short verbatim quote or close substring from the passage.\n"
        "- rationale may explain relevance, but claim_text itself must remain tightly span-grounded.\n"
        "- Return JSON only.\n"
    )
