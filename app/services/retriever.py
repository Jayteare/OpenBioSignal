"""Simple lexical retrieval utilities for chunk ranking."""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.db.models import Chunk

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
RESULT_SIGNAL_TERMS = (
    "result",
    "results",
    "conclusion",
    "conclusions",
    "found",
    "observed",
    "improved",
    "reduced",
    "increased",
    "decreased",
    "associated",
    "effect",
    "significant",
    "no significant difference",
    "compared with",
    "placebo",
    "confidence interval",
    "ci",
    "p <",
    "odds ratio",
    "relative risk",
    "subgroup",
    "benefit",
)
RESULT_SECTION_TERMS = ("result", "results", "conclusion", "conclusions", "discussion")
BACKGROUND_METHODS_TERMS = (
    "background",
    "objective",
    "objectives",
    "methods",
    "search strategy",
    "we searched",
    "included trials",
    "was conducted",
    "this meta-analysis investigated",
    "aim of the study",
    "participants were included",
    "eligibility criteria",
)
BACKGROUND_METHODS_SECTION_TERMS = ("background", "objective", "objectives", "methods")


def score_chunk_for_query(query: str, chunk_text: str) -> float:
    """Score a chunk against a query using simple lexical overlap."""

    query_tokens = _tokenize(query)
    chunk_tokens = _tokenize(chunk_text)
    if not query_tokens or not chunk_tokens:
        return 0.0

    query_counts = Counter(query_tokens)
    chunk_counts = Counter(chunk_tokens)
    matched_terms = [token for token in query_counts if token in chunk_counts]

    if not matched_terms:
        return 0.0

    coverage_score = len(matched_terms) / len(query_counts)
    frequency_score = sum(min(chunk_counts[token], query_counts[token] + 1) for token in matched_terms) / len(query_tokens)
    return round(coverage_score + (0.2 * frequency_score), 4)


def result_signal_score(chunk_text: str, section: str | None = None) -> float:
    """Return a modest boost for chunks that look like findings or conclusions."""

    normalized_text = chunk_text.lower()
    normalized_section = (section or "").lower()
    section_boost = 0.1 if any(term in normalized_section for term in RESULT_SECTION_TERMS) else 0.0
    term_matches = sum(1 for term in RESULT_SIGNAL_TERMS if term in normalized_text)
    term_boost = min(term_matches * 0.04, 0.24)
    return round(section_boost + term_boost, 4)


def background_or_methods_penalty(chunk_text: str, section: str | None = None) -> float:
    """Return a conservative penalty for chunks that look mostly introductory or methodological."""

    normalized_text = chunk_text.lower()
    normalized_section = (section or "").lower()
    result_boost = result_signal_score(chunk_text, section)
    if result_boost >= 0.12:
        return 0.0

    section_penalty = 0.08 if any(term in normalized_section for term in BACKGROUND_METHODS_SECTION_TERMS) else 0.0
    term_matches = sum(1 for term in BACKGROUND_METHODS_TERMS if term in normalized_text)
    term_penalty = min(term_matches * 0.04, 0.16)
    return round(section_penalty + term_penalty, 4)


def compute_chunk_ranking_breakdown(query: str, chunk_text: str, section: str | None = None) -> dict[str, float]:
    """Return lexical score, heuristic adjustments, and final score for one chunk."""

    lexical_score = score_chunk_for_query(query, chunk_text)
    signal_score = result_signal_score(chunk_text, section) if lexical_score > 0 else 0.0
    methods_penalty = background_or_methods_penalty(chunk_text, section) if lexical_score > 0 else 0.0
    final_score = max(0.0, lexical_score + signal_score - methods_penalty)
    return {
        "lexical_score": round(lexical_score, 4),
        "result_signal_score": round(signal_score, 4),
        "methods_penalty": round(methods_penalty, 4),
        "final_score": round(final_score, 4),
    }


def rank_chunks_for_run(query: str, chunks: list[Chunk]) -> list[tuple[Chunk, float]]:
    """Return chunks ranked by descending lexical score plus lightweight heuristics."""

    ranked_chunks = [
        (chunk, compute_chunk_ranking_breakdown(query, chunk.text, chunk.section)["final_score"]) for chunk in chunks
    ]
    return sorted(ranked_chunks, key=lambda item: (-item[1], item[0].chunk_index, item[0].document_id))


def _tokenize(text: str) -> list[str]:
    """Normalize and tokenize free text into simple lexical terms."""

    return [token for token in TOKEN_PATTERN.findall(text.lower()) if len(token) > 1]
