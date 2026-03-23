from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DocumentRecord(BaseModel):
    """Minimal document metadata captured during a run."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    pmid: str | None = None
    title: str
    journal: str | None = None
    pubdate: str | None = None
    authors: str | None = None
    source: str = "pubmed"
    source_url: str | None = None
    abstract: str | None = None
    has_abstract: bool = False
    chunk_count: int = 0


class RunDocumentsResponse(BaseModel):
    """Collection of persisted candidate papers for a research run."""

    run_id: str
    question: str
    documents_count: int
    documents: list[DocumentRecord] = Field(default_factory=list)


class RunSearchResponse(BaseModel):
    """Result of running a PubMed search for a research run."""

    run_id: str
    question: str
    documents_found: int
    documents: list[DocumentRecord] = Field(default_factory=list)


class AbstractFetchResponse(BaseModel):
    """Result of fetching PubMed abstracts for a saved run."""

    run_id: str
    documents_total: int
    documents_updated: int
    missing_abstract_count: int
    status: str
