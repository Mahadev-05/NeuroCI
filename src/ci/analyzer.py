"""Minimal CI failure analysis for GitHub Actions workflow_run events."""

from __future__ import annotations

from typing import Any

from src.models import CIFailureAnalysis


def analyze_workflow_failure(payload: dict[str, Any]) -> CIFailureAnalysis:
    """
    Build a beginner-friendly failure analysis from a GitHub workflow_run payload.

    The workflow_run webhook does not include full job logs by default, so this
    analyzer only uses fields present in the payload and links back to GitHub logs
    when a logs URL is available.
    """
    workflow_run = payload.get("workflow_run") or {}
    repository = payload.get("repository") or {}

    run_id = int(workflow_run.get("id") or 0)
    workflow_name = str(workflow_run.get("name") or workflow_run.get("display_title") or "unknown")
    failed_job = _extract_failed_job(workflow_run)
    branch = str(workflow_run.get("head_branch") or repository.get("default_branch") or "unknown")
    commit_sha = str(workflow_run.get("head_sha") or "")
    repo_name = str(repository.get("full_name") or "unknown")
    conclusion = str(workflow_run.get("conclusion") or "unknown")
    run_url = str(workflow_run.get("html_url") or "")
    logs_url = str(workflow_run.get("logs_url") or "")

    failure_type = classify_failure(workflow_name, failed_job, workflow_run)
    suggestions = remediation_suggestions(failure_type)
    summary = (
        f"{workflow_name} failed on branch {branch} for {repo_name}. "
        f"Likely category: {failure_type}. "
        f"Failed job: {failed_job}."
    )

    return CIFailureAnalysis(
        run_id=run_id,
        repository=repo_name,
        workflow_name=workflow_name,
        failed_job=failed_job,
        branch=branch,
        commit_sha=commit_sha,
        conclusion=conclusion,
        run_url=run_url,
        logs_url=logs_url,
        failure_type=failure_type,
        summary=summary,
        remediation_suggestions=suggestions,
    )


def classify_failure(workflow_name: str, failed_job: str, workflow_run: dict[str, Any]) -> str:
    """Classify likely CI failure type using simple, explainable heuristics."""
    haystack = " ".join(
        [
            workflow_name,
            failed_job,
            str(workflow_run.get("display_title") or ""),
            str(workflow_run.get("path") or ""),
            str(workflow_run.get("event") or ""),
        ]
    ).lower()

    if any(term in haystack for term in ("pytest config", "test discovery", "pytest.ini")):
        return "simple pytest config issue"
    if any(term in haystack for term in ("requirements.txt", "requirements mismatch")):
        return "requirements.txt mismatch"
    if any(term in haystack for term in ("pip", "dependency", "module not found", "modulenotfounderror")):
        return "dependency missing"
    if any(term in haystack for term in ("github actions", "workflow yaml", "actions/setup-python")):
        return "basic GitHub Actions YAML issue"
    if any(term in haystack for term in ("docker", "build image", "container")):
        return "Docker build failed"
    if "format" in haystack:
        return "formatting issue"
    if any(term in haystack for term in ("lint", "ruff", "flake8", "eslint", "format")):
        return "linting failed"
    if any(term in haystack for term in ("pytest", "test", "unit")):
        return "pytest failed"
    if "syntax" in haystack:
        return "syntax error"
    if any(term in haystack for term in ("import", "module")):
        return "import error"
    if any(term in haystack for term in ("secret", "token", "permission", "auth")):
        return "GitHub Actions secrets or permissions issue"
    return "unknown CI failure"


def remediation_suggestions(failure_type: str) -> list[str]:
    """Return safe, human-readable next steps without modifying code."""
    suggestions_by_type = {
        "pytest failed": [
            "Run pytest locally and inspect the failing assertion.",
            "Check whether recent code changes altered expected behavior.",
            "Review test fixtures and environment-specific assumptions.",
        ],
        "dependency missing": [
            "Run pip install -r requirements.txt.",
            "Check that new imports are listed in requirements.txt or pyproject.toml.",
            "Verify the GitHub Actions job uses the expected Python version.",
        ],
        "Docker build failed": [
            "Check Dockerfile COPY paths and build context.",
            "Run docker build locally with the same Dockerfile.",
            "Verify required files are not excluded by .dockerignore.",
        ],
        "linting failed": [
            "Run the configured linter locally.",
            "Fix formatting, unused imports, or style violations reported by CI.",
            "Confirm local linter versions match the CI environment.",
        ],
        "syntax error": [
            "Run python -m py_compile on the changed Python files.",
            "Check the line reported by the GitHub Actions log.",
            "Look for missing colons, brackets, quotes, or indentation errors.",
        ],
        "import error": [
            "Verify the import path and package name.",
            "Check whether __init__.py files are present where needed.",
            "Run tests from the repository root to match CI import behavior.",
        ],
        "GitHub Actions secrets or permissions issue": [
            "Verify GitHub Actions secrets and repository permissions.",
            "Check token scopes for API or package registry access.",
            "Confirm protected environment approvals are configured correctly.",
        ],
    }
    return suggestions_by_type.get(
        failure_type,
        [
            "Open the GitHub Actions run and inspect the failed job logs.",
            "Re-run the workflow after confirming environment variables and secrets.",
            "Compare the failing commit with the last successful run.",
        ],
    )


def _extract_failed_job(workflow_run: dict[str, Any]) -> str:
    """
    Extract a failed job name when a simplified jobs list is present.

    GitHub's workflow_run webhook normally provides a jobs_url rather than the
    full jobs list. Tests and local demos may include a minimal jobs list.
    """
    jobs = workflow_run.get("jobs")
    if isinstance(jobs, list):
        for job in jobs:
            if isinstance(job, dict) and job.get("conclusion") == "failure":
                return str(job.get("name") or job.get("id") or "unknown")

    return str(
        workflow_run.get("failed_job")
        or workflow_run.get("display_title")
        or workflow_run.get("name")
        or "unknown"
    )
