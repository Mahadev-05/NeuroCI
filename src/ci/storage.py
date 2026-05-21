"""Lightweight JSON persistence for CI failure analyses."""

from __future__ import annotations

import json
from pathlib import Path

import structlog

from src.config import get_settings
from src.models import CIFailureAnalysis, CIRemediationRecord

logger = structlog.get_logger()


def save_failure_analysis(analysis: CIFailureAnalysis, max_records: int = 100) -> None:
    """Persist a CI failure analysis to a small local JSON file."""
    path = _store_path()
    failures = list_failure_analyses(limit=max_records)
    failures = [item for item in failures if item.run_id != analysis.run_id]
    failures.insert(0, analysis)
    failures = failures[:max_records]

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    data = [item.model_dump(mode="json") for item in failures]
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp_path.replace(path)

    logger.info(
        "ci.failure_analysis.stored",
        run_id=analysis.run_id,
        repo=analysis.repository,
        workflow=analysis.workflow_name,
        failure_type=analysis.failure_type,
    )


def list_failure_analyses(limit: int = 20) -> list[CIFailureAnalysis]:
    """Return recent CI failure analyses, newest first."""
    path = _store_path()
    if not path.exists():
        return []

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return []
        return [CIFailureAnalysis(**item) for item in raw[:limit] if isinstance(item, dict)]
    except Exception as exc:
        logger.warning("ci.failure_analysis.read_failed", error=str(exc), path=str(path))
        return []


def save_remediation_record(record: CIRemediationRecord, max_records: int = 100) -> None:
    """Persist a remediation attempt to a small local JSON file."""
    path = _remediation_store_path()
    records = list_remediation_records(limit=max_records)
    records = [item for item in records if item.run_id != record.run_id]
    records.insert(0, record)
    records = records[:max_records]

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    data = [item.model_dump(mode="json") for item in records]
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp_path.replace(path)

    logger.info(
        "ci.remediation.stored",
        run_id=record.run_id,
        repo=record.repository,
        status=record.status,
        branch=record.branch_name,
        pr_url=record.pr_url,
        dry_run=record.dry_run,
    )


def list_remediation_records(limit: int = 20) -> list[CIRemediationRecord]:
    """Return recent remediation attempts, newest first."""
    path = _remediation_store_path()
    if not path.exists():
        return []

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return []
        return [CIRemediationRecord(**item) for item in raw[:limit] if isinstance(item, dict)]
    except Exception as exc:
        logger.warning("ci.remediation.read_failed", error=str(exc), path=str(path))
        return []


def has_remediation_for_run(run_id: int) -> bool:
    """Prevent more than one remediation attempt per workflow run."""
    return any(record.run_id == run_id for record in list_remediation_records(limit=100))


def _store_path() -> Path:
    settings = get_settings()
    path = Path(settings.ci_failure_store_path)
    if path.is_absolute():
        return path
    return settings.project_root / path


def _remediation_store_path() -> Path:
    settings = get_settings()
    path = Path(settings.ci_remediation_store_path)
    if path.is_absolute():
        return path
    return settings.project_root / path
