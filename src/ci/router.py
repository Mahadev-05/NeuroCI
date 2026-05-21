"""API routes for CI failure monitoring."""

from __future__ import annotations

from fastapi import APIRouter, Query

from src.ci.storage import list_failure_analyses, list_remediation_records
from src.models import CIFailureListResponse, CIRemediationListResponse

router = APIRouter()


@router.get("/ci/failures", response_model=CIFailureListResponse, summary="List CI failures")
async def list_ci_failures(limit: int = Query(default=20, ge=1, le=100)) -> CIFailureListResponse:
    """Return recent GitHub Actions failure analyses."""
    failures = list_failure_analyses(limit=limit)
    return CIFailureListResponse(failures=failures, count=len(failures))


@router.get(
    "/ci/remediations",
    response_model=CIRemediationListResponse,
    summary="List CI remediation attempts",
)
async def list_ci_remediations(
    limit: int = Query(default=20, ge=1, le=100),
) -> CIRemediationListResponse:
    """Return recent automated remediation attempts."""
    remediations = list_remediation_records(limit=limit)
    return CIRemediationListResponse(remediations=remediations, count=len(remediations))
