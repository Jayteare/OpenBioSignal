"""Helpers for persisting and reading lightweight pipeline debug snapshots."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from app.db.models import ResearchRun


def persist_pipeline_debug(run: ResearchRun, summary: dict[str, Any], errors: list[str]) -> None:
    """Persist the latest pipeline summary and errors onto a run."""

    run.last_pipeline_summary_json = json.dumps(summary, ensure_ascii=True)
    run.last_pipeline_errors_json = json.dumps(errors, ensure_ascii=True)
    run.last_pipeline_run_at = datetime.utcnow()


def build_pipeline_debug_payload(run: ResearchRun) -> dict[str, Any]:
    """Return a normalized view of the latest persisted pipeline debug data."""

    summary = _deserialize_dict(run.last_pipeline_summary_json)
    errors = _deserialize_string_list(run.last_pipeline_errors_json)
    steps = summary.get("steps", {}) if isinstance(summary.get("steps"), dict) else {}
    extract_claims = steps.get("extract_claims", {}) if isinstance(steps.get("extract_claims"), dict) else {}

    return {
        "run_id": run.id,
        "question": run.question,
        "status": str(summary.get("status") or run.status),
        "has_pipeline_debug": bool(run.last_pipeline_run_at or summary or errors),
        "last_pipeline_run_at": run.last_pipeline_run_at,
        "documents_total": int(summary.get("documents_total", 0) or 0),
        "abstracts_available": int(summary.get("abstracts_available", 0) or 0),
        "chunks_total": int(summary.get("chunks_total", 0) or 0),
        "ranked_chunks": int(summary.get("ranked_chunks", 0) or 0),
        "claims_total": int(summary.get("claims_total", 0) or 0),
        "brief_generated": bool(summary.get("brief_generated", False)),
        "brief_id": summary.get("brief_id"),
        "steps": steps,
        "errors": errors,
        "error_count": len(errors),
        "claim_extraction_attempted": bool(extract_claims.get("extraction_attempts", 0)),
        "claim_extraction_failed": bool(extract_claims.get("extraction_failures", 0)),
    }


def _deserialize_dict(value: str | None) -> dict[str, Any]:
    """Deserialize a JSON object string into a Python dict."""

    if not value:
        return {}

    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        payload = {}

    return payload if isinstance(payload, dict) else {}


def _deserialize_string_list(value: str | None) -> list[str]:
    """Deserialize a JSON list of strings into a Python list."""

    if not value:
        return []

    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        payload = []

    if not isinstance(payload, list):
        return []

    return [str(item).strip() for item in payload if str(item).strip()]
