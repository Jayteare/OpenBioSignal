from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ResearchRun(Base):
    """Represents a single research question run."""

    __tablename__ = "research_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="created", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_pipeline_summary_json: Mapped[str | None] = mapped_column(Text)
    last_pipeline_errors_json: Mapped[str | None] = mapped_column(Text)
    last_pipeline_run_at: Mapped[datetime | None] = mapped_column(DateTime)

    documents: Mapped[list[Document]] = relationship("Document", back_populates="run", cascade="all, delete-orphan")
    brief: Mapped[Brief | None] = relationship("Brief", back_populates="run", uselist=False, cascade="all, delete-orphan")


class Document(Base):
    """Represents a literature document collected for a run."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id"), nullable=False)
    pmid: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    journal: Mapped[str | None] = mapped_column(String(500))
    pubdate: Mapped[str | None] = mapped_column(String(100))
    authors: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(100), default="pubmed", nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    abstract: Mapped[str | None] = mapped_column(Text)

    run: Mapped[ResearchRun] = relationship("ResearchRun", back_populates="documents")
    chunks: Mapped[list[Chunk]] = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    """Represents a document chunk prepared for retrieval or extraction."""

    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id"), nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[str] = mapped_column(String(100), nullable=False, default="abstract")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    retrieval_score: Mapped[float | None] = mapped_column(Float)

    document: Mapped[Document] = relationship("Document", back_populates="chunks")
    claims: Mapped[list[Claim]] = relationship("Claim", back_populates="chunk", cascade="all, delete-orphan")


class Claim(Base):
    """Represents a structured claim extracted from a chunk."""

    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id"), nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False)
    chunk_id: Mapped[str] = mapped_column(ForeignKey("chunks.id"), nullable=False)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    stance: Mapped[str | None] = mapped_column(String(50))
    relevance: Mapped[str | None] = mapped_column(String(20))
    study_type: Mapped[str | None] = mapped_column(String(255))
    population: Mapped[str | None] = mapped_column(Text)
    intervention_or_exposure: Mapped[str | None] = mapped_column(Text)
    comparator: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(Text)
    direction_of_effect: Mapped[str | None] = mapped_column(String(100))
    limitations: Mapped[str | None] = mapped_column(Text)
    uncertainty_note: Mapped[str | None] = mapped_column(Text)
    evidence_span: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
    stance_adjustment_note: Mapped[str | None] = mapped_column(Text)
    claim_repair_note: Mapped[str | None] = mapped_column(Text)
    evaluation_json: Mapped[str | None] = mapped_column(Text)
    evaluation_overall_score: Mapped[float | None] = mapped_column(Float)
    evaluation_verdict: Mapped[str | None] = mapped_column(String(20))
    confidence: Mapped[float | None] = mapped_column(Float)
    evidence_direction: Mapped[str | None] = mapped_column(String(100))

    run: Mapped[ResearchRun] = relationship("ResearchRun")
    document: Mapped[Document] = relationship("Document")
    chunk: Mapped[Chunk] = relationship("Chunk", back_populates="claims")


class Brief(Base):
    """Represents the grounded evidence brief for a run."""

    __tablename__ = "briefs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id"), unique=True, nullable=False)
    direct_answer: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="TODO: generate grounded evidence brief.")
    supporting_findings: Mapped[str | None] = mapped_column(Text)
    conflicting_findings: Mapped[str | None] = mapped_column(Text)
    caveats: Mapped[str | None] = mapped_column(Text)
    evidence_table_json: Mapped[str | None] = mapped_column(Text)
    markdown_report: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    run: Mapped[ResearchRun] = relationship("ResearchRun", back_populates="brief")
