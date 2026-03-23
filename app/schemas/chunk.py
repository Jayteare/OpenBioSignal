from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ChunkRecord(BaseModel):
    """Minimal text chunk linked to a source document."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    document_id: str
    document_title: str | None = None
    chunk_index: int
    section: str
    text: str
    retrieval_score: float | None = None
    lexical_score: float | None = None
    result_signal_score: float | None = None
    methods_penalty: float | None = None


class RunChunksResponse(BaseModel):
    """Collection of persisted chunks for a research run."""

    run_id: str
    chunks_count: int
    chunks: list[ChunkRecord] = Field(default_factory=list)


class DocumentChunksResponse(BaseModel):
    """Collection of persisted chunks for a saved document."""

    document_id: str
    run_id: str
    chunks_count: int
    chunks: list[ChunkRecord] = Field(default_factory=list)


class ChunkingResponse(BaseModel):
    """Summary of abstract chunk creation for a research run."""

    run_id: str
    documents_with_abstracts: int
    documents_chunked: int
    chunks_created: int
    status: str


class RankedChunksResponse(BaseModel):
    """Summary of lexical chunk ranking for a research run."""

    run_id: str
    question: str
    chunks_total: int
    chunks_ranked: int
    top_chunks: list[ChunkRecord] = Field(default_factory=list)


class TopChunksResponse(BaseModel):
    """Top-ranked chunks for a research run."""

    run_id: str
    question: str
    limit: int
    chunks_count: int
    chunks: list[ChunkRecord] = Field(default_factory=list)
