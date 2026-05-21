"""Tests for safe CI remediation planning."""

from unittest.mock import MagicMock, patch

from src.ci.remediator import build_branch_name, generate_remediation_plan, process_remediation
from src.models import CIFailureAnalysis


def _analysis(failure_type: str, summary: str = "") -> CIFailureAnalysis:
    return CIFailureAnalysis(
        run_id=12345,
        repository="owner/repo",
        workflow_name="CI",
        failed_job="ModuleNotFoundError: No module named 'requests'",
        branch="main",
        commit_sha="abc123def456",
        conclusion="failure",
        run_url="https://github.com/owner/repo/actions/runs/12345",
        failure_type=failure_type,
        summary=summary or "CI failed with ModuleNotFoundError: No module named 'requests'",
        remediation_suggestions=["Add the missing dependency."],
    )


def test_branch_name_is_deterministic_and_safe():
    analysis = _analysis("dependency missing")

    assert build_branch_name(analysis) == "neuroci/autofix-12345-repo-dependency-missing"


def test_dependency_remediation_generation_appends_requirement():
    analysis = _analysis("dependency missing")

    plan = generate_remediation_plan(
        analysis,
        file_loader=lambda path: "fastapi>=0.115.0\n" if path == "requirements.txt" else "",
    )

    assert plan is not None
    assert plan.pr_title == "[NeuroCI AutoFix] Fix CI failure: dependency missing"
    assert plan.patches[0].file_path == "requirements.txt"
    assert "requests\n" in plan.patches[0].new_content
    assert "AI-generated" in plan.pr_body
    assert "manual review" in plan.pr_body


def test_unsupported_failure_returns_no_plan():
    analysis = _analysis("Docker build failed")

    assert generate_remediation_plan(analysis) is None


def test_dry_run_remediation_does_not_call_github():
    analysis = _analysis("dependency missing")
    settings = MagicMock()
    settings.github_remediation_enabled = True
    settings.github_remediation_dry_run = True
    settings.github_token = "token"

    with (
        patch("src.ci.remediator.has_remediation_for_run", return_value=False),
        patch("src.ci.remediator.save_remediation_record") as save_record,
    ):
        record = process_remediation(analysis, settings)

    assert record.status == "dry_run"
    assert record.branch_name == "neuroci/autofix-12345-repo-dependency-missing"
    assert record.files_changed == ["requirements.txt"]
    save_record.assert_called_once()


def test_existing_remediation_is_skipped():
    analysis = _analysis("dependency missing")
    settings = MagicMock()
    settings.github_remediation_enabled = True
    settings.github_remediation_dry_run = False

    with patch("src.ci.remediator.has_remediation_for_run", return_value=True):
        record = process_remediation(analysis, settings)

    assert record.status == "skipped"
    assert record.reason == "remediation_already_attempted"
