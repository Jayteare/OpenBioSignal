from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def initialize_database() -> None:
    """Create tables and apply lightweight local SQLite schema updates."""

    Base.metadata.create_all(bind=engine)

    if settings.database_url.startswith("sqlite"):
        _ensure_sqlite_research_run_columns()
        _ensure_sqlite_document_columns()
        _ensure_sqlite_chunk_columns()
        _ensure_sqlite_claim_columns()
        _ensure_sqlite_brief_columns()


def _ensure_sqlite_research_run_columns() -> None:
    """Add run debug columns for local SQLite development if missing."""

    inspector = inspect(engine)
    if "research_runs" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("research_runs")}
    column_definitions = {
        "last_pipeline_summary_json": "TEXT",
        "last_pipeline_errors_json": "TEXT",
        "last_pipeline_run_at": "DATETIME",
    }

    with engine.begin() as connection:
        for column_name, column_type in column_definitions.items():
            if column_name not in existing_columns:
                connection.execute(text(f"ALTER TABLE research_runs ADD COLUMN {column_name} {column_type}"))


def _ensure_sqlite_document_columns() -> None:
    """Add document metadata columns for local SQLite development if missing."""

    inspector = inspect(engine)
    if "documents" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("documents")}
    column_definitions = {
        "pmid": "VARCHAR(32)",
        "journal": "VARCHAR(500)",
        "pubdate": "VARCHAR(100)",
        "authors": "TEXT",
        "abstract": "TEXT",
    }

    with engine.begin() as connection:
        for column_name, column_type in column_definitions.items():
            if column_name not in existing_columns:
                connection.execute(text(f"ALTER TABLE documents ADD COLUMN {column_name} {column_type}"))


def _ensure_sqlite_chunk_columns() -> None:
    """Add chunk metadata columns for local SQLite development if missing."""

    inspector = inspect(engine)
    if "chunks" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("chunks")}
    column_definitions = {
        "run_id": "VARCHAR(36)",
        "chunk_index": "INTEGER",
        "section": "VARCHAR(100)",
        "retrieval_score": "FLOAT",
    }

    with engine.begin() as connection:
        for column_name, column_type in column_definitions.items():
            if column_name not in existing_columns:
                connection.execute(text(f"ALTER TABLE chunks ADD COLUMN {column_name} {column_type}"))

        if "run_id" not in existing_columns:
            connection.execute(
                text(
                    "UPDATE chunks SET run_id = (SELECT documents.run_id FROM documents WHERE documents.id = chunks.document_id) "
                    "WHERE run_id IS NULL"
                )
            )

        if "chunk_index" not in existing_columns and "ordinal" in existing_columns:
            connection.execute(text("UPDATE chunks SET chunk_index = ordinal WHERE chunk_index IS NULL"))

        if "section" not in existing_columns:
            connection.execute(text("UPDATE chunks SET section = 'abstract' WHERE section IS NULL"))


def _ensure_sqlite_claim_columns() -> None:
    """Add claim metadata columns for local SQLite development if missing."""

    inspector = inspect(engine)
    if "claims" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("claims")}
    column_definitions = {
        "run_id": "VARCHAR(36)",
        "document_id": "VARCHAR(36)",
        "stance": "VARCHAR(50)",
        "relevance": "VARCHAR(20)",
        "study_type": "VARCHAR(255)",
        "population": "TEXT",
        "intervention_or_exposure": "TEXT",
        "comparator": "TEXT",
        "outcome": "TEXT",
        "direction_of_effect": "VARCHAR(100)",
        "limitations": "TEXT",
        "uncertainty_note": "TEXT",
        "evidence_span": "TEXT",
        "rationale": "TEXT",
        "stance_adjustment_note": "TEXT",
        "claim_repair_note": "TEXT",
        "evaluation_json": "TEXT",
        "evaluation_overall_score": "FLOAT",
        "evaluation_verdict": "VARCHAR(20)",
    }

    with engine.begin() as connection:
        for column_name, column_type in column_definitions.items():
            if column_name not in existing_columns:
                connection.execute(text(f"ALTER TABLE claims ADD COLUMN {column_name} {column_type}"))

        if "run_id" not in existing_columns:
            connection.execute(
                text(
                    "UPDATE claims SET run_id = (SELECT chunks.run_id FROM chunks WHERE chunks.id = claims.chunk_id) "
                    "WHERE run_id IS NULL"
                )
            )

        if "document_id" not in existing_columns:
            connection.execute(
                text(
                    "UPDATE claims SET document_id = (SELECT chunks.document_id FROM chunks WHERE chunks.id = claims.chunk_id) "
                    "WHERE document_id IS NULL"
                )
            )


def _ensure_sqlite_brief_columns() -> None:
    """Add brief synthesis columns for local SQLite development if missing."""

    inspector = inspect(engine)
    if "briefs" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("briefs")}
    column_definitions = {
        "direct_answer": "TEXT",
        "supporting_findings": "TEXT",
        "conflicting_findings": "TEXT",
        "caveats": "TEXT",
        "evidence_table_json": "TEXT",
        "markdown_report": "TEXT",
    }

    with engine.begin() as connection:
        for column_name, column_type in column_definitions.items():
            if column_name not in existing_columns:
                connection.execute(text(f"ALTER TABLE briefs ADD COLUMN {column_name} {column_type}"))


def get_db() -> Generator[Session, None, None]:
    """Yield a database session for request-scoped usage."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
