"""Small helpers for normalizing user-facing LLM error messages."""

from __future__ import annotations


def normalize_llm_error_message(error: Exception | str) -> str:
    """Return a concise, friendlier message for common LLM failures."""

    raw_message = str(error).strip() if not isinstance(error, str) else error.strip()
    if not raw_message:
        return "An unexpected LLM error occurred."

    lowered = raw_message.lower()
    quota_markers = (
        "exceeded your current quota",
        "insufficient_quota",
        "billing",
        "quota",
        "credits",
        "plan",
        "429",
        "rate limit",
        "too many requests",
    )
    if any(marker in lowered for marker in quota_markers):
        return "Z.AI API quota or billing limit reached. Check your API key, billing, credits, and model access."

    cleaned = " ".join(raw_message.split())
    return cleaned[:220]
