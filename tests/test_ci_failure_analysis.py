"""Tests for minimal CI failure detection and analysis."""

from src.ci.analyzer import analyze_workflow_failure


def test_analyze_failed_pytest_workflow():
    payload = {
        "action": "completed",
        "workflow_run": {
            "id": 12345,
            "name": "pytest",
            "head_branch": "feature/demo",
            "head_sha": "abc123def456",
            "conclusion": "failure",
            "html_url": "https://github.com/owner/repo/actions/runs/12345",
            "logs_url": "https://api.github.com/repos/owner/repo/actions/runs/12345/logs",
            "jobs": [{"name": "unit tests", "conclusion": "failure"}],
        },
        "repository": {"full_name": "owner/repo", "default_branch": "main"},
    }

    analysis = analyze_workflow_failure(payload)

    assert analysis.run_id == 12345
    assert analysis.repository == "owner/repo"
    assert analysis.workflow_name == "pytest"
    assert analysis.failed_job == "unit tests"
    assert analysis.branch == "feature/demo"
    assert analysis.commit_sha == "abc123def456"
    assert analysis.conclusion == "failure"
    assert analysis.logs_url.endswith("/logs")
    assert analysis.failure_type == "pytest failed"
    assert "Run pytest locally" in analysis.remediation_suggestions[0]


def test_analyze_unsupported_payload_falls_back_safely():
    analysis = analyze_workflow_failure({"workflow_run": {}, "repository": {}})

    assert analysis.run_id == 0
    assert analysis.repository == "unknown"
    assert analysis.workflow_name == "unknown"
    assert analysis.failed_job == "unknown"
    assert analysis.failure_type == "unknown CI failure"
    assert analysis.remediation_suggestions
