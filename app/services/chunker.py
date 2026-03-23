"""Utilities for splitting saved abstracts into retrieval-ready chunks."""

from __future__ import annotations

import re
from typing import Any


def chunk_text(text: str, max_chars: int = 800, overlap_chars: int = 120) -> list[str]:
    """Split text into ordered chunks using paragraph-aware fallbacks."""

    cleaned_text = text.strip()
    if not cleaned_text:
        return []

    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n+", cleaned_text) if paragraph.strip()]
    segments = paragraphs if len(paragraphs) > 1 else _split_into_sentences(cleaned_text)
    return _build_chunks(segments=segments, max_chars=max_chars, overlap_chars=overlap_chars)


def chunk_document_abstract(document: Any) -> list[dict[str, int | str]]:
    """Return normalized chunk records for a saved document abstract."""

    abstract_text = getattr(document, "abstract", None) or ""
    return [
        {
            "chunk_index": index,
            "section": "abstract",
            "text": chunk,
        }
        for index, chunk in enumerate(chunk_text(abstract_text))
    ]


def _split_into_sentences(text: str) -> list[str]:
    """Split text into readable sentence-like units."""

    sentences = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", text) if segment.strip()]
    return sentences or [text.strip()]


def _build_chunks(segments: list[str], max_chars: int, overlap_chars: int) -> list[str]:
    """Assemble segments into overlapping character-bounded chunks."""

    chunks: list[str] = []
    current = ""

    for segment in segments:
        if not current:
            current = segment
            continue

        candidate = f"{current}\n\n{segment}"
        if len(candidate) <= max_chars:
            current = candidate
            continue

        chunks.extend(_split_long_chunk(current, max_chars=max_chars, overlap_chars=overlap_chars))
        current = segment

    if current:
        chunks.extend(_split_long_chunk(current, max_chars=max_chars, overlap_chars=overlap_chars))

    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _split_long_chunk(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    """Split a long text block with a simple overlapping window."""

    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    step = max(max_chars - overlap_chars, 1)

    while start < len(text):
        end = min(start + max_chars, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start += step

    return chunks
