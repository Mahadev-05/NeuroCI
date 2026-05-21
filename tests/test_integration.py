"""
NeuroCI — Integration Tests.

Tests for the full webhook→dispatch flow with mocked dependencies.
"""
import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

WEBHOOK_SECRET = "test-secret-123"

VALID_WORKFLOW_RUN = {
    "action": "completed",
    "workflow_run": {
        "id": 12345, "name": "CI", "head_branch": "feature/test",
        "head_sha": "abc123def456", "conclusion": "failure",
        "html_url": "https://github.com/o/r/actions/runs/12345",
        "run_attempt": 1, "logs_url": "",
    },
    "repository": {
        "id": 1, "full_name": "owner/repo",
        "html_url": "https://github.com/owner/repo",
        "default_branch": "main",
    },
}

VALID_PR_MERGED = {
    "action": "closed",
    "pull_request": {
        "number": 42,
        "title": "🧠 NeuroCI: Fix ImportError (run #12345)",
        "merged": True,
        "body": "Auto-repair by NeuroCI",
    },
    "repository": {"full_name": "owner/repo"},
}

VALID_PR_REJECTED = {
    "action": "closed",
    "pull_request": {
        "number": 43,
        "title": "🧠 NeuroCI: Fix SyntaxError (run #67890)",
        "merged": False,
        "body": "Rejected PR",
    },
    "repository": {"full_name": "owner/repo"},
}


def _sign(payload: dict, secret: str) -> str:
    body = json.dumps(payload).encode()
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class TestWebhookIntegration:
    """Test webhook receiver with mocked settings."""

    def _get_client(self):
        with patch("src.config.get_settings") as ms:
            s = MagicMock()
            s.github_webhook_secret = WEBHOOK_SECRET
            s.github_allowed_repos = ["owner/repo"]
            s.log_level = "INFO"
            s.redis_url = "redis://localhost:6379/0"
            s.chroma_host = "localhost"
            s.chroma_port = 8000
            s.opa_url = "http://localhost:8181"
            s.ci_failure_store_path = "data/ci_failures.json"
            s.ci_remediation_store_path = "data/ci_remediations.json"
            s.github_remediation_enabled = False
            s.github_remediation_dry_run = True
            s.is_repo_allowed.return_value = True
            ms.return_value = s
            from fastapi.testclient import TestClient

            from src.main import app
            return TestClient(app)

    def test_missing_signature_returns_403(self):
        """Missing signature should return 403."""
        client = self._get_client()
        resp = client.post("/api/v1/webhook/github", json=VALID_WORKFLOW_RUN)
        assert resp.status_code == 403

    def test_invalid_signature_returns_403(self):
        """Wrong signature should return 403."""
        client = self._get_client()
        resp = client.post(
            "/api/v1/webhook/github",
            content=json.dumps(VALID_WORKFLOW_RUN),
            headers={
                "X-Hub-Signature-256": "sha256=invalid",
                "X-GitHub-Event": "workflow_run",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 403

    def test_success_conclusion_ignored(self):
        """Non-failure conclusion should be ignored."""
        payload = {**VALID_WORKFLOW_RUN}
        payload["workflow_run"] = {**VALID_WORKFLOW_RUN["workflow_run"], "conclusion": "success"}
        body = json.dumps(payload).encode()
        sig = _sign(payload, WEBHOOK_SECRET)

        client = self._get_client()
        resp = client.post(
            "/api/v1/webhook/github",
            content=body,
            headers={
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "workflow_run",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["accepted"] is False

    def test_failed_workflow_generates_ci_analysis(self):
        """Failed completed workflow_run events should be analyzed."""
        payload = {**VALID_WORKFLOW_RUN}
        payload["workflow_run"] = {
            **VALID_WORKFLOW_RUN["workflow_run"],
            "name": "pytest",
            "logs_url": "https://api.github.com/repos/owner/repo/actions/runs/12345/logs",
            "jobs": [{"name": "unit tests", "conclusion": "failure"}],
        }
        body = json.dumps(payload).encode()
        sig = _sign(payload, WEBHOOK_SECRET)

        client = self._get_client()
        with (
            patch("src.webhook.receiver._is_duplicate", return_value=False),
            patch("src.webhook.receiver.save_failure_analysis") as save_analysis,
            patch("src.webhook.receiver.process_remediation") as process_remediation,
        ):
            process_remediation.return_value.status = "skipped"
            resp = client.post(
                "/api/v1/webhook/github",
                content=body,
                headers={
                    "X-Hub-Signature-256": sig,
                    "X-GitHub-Event": "workflow_run",
                    "Content-Type": "application/json",
                },
            )

        assert resp.status_code == 202
        data = resp.json()
        assert data["accepted"] is True
        assert data["message"] == "CI failure analyzed: pytest failed; remediation skipped"
        save_analysis.assert_called_once()
        process_remediation.assert_called_once()
        analysis = save_analysis.call_args.args[0]
        assert analysis.workflow_name == "pytest"
        assert analysis.failed_job == "unit tests"
        assert analysis.repository == "owner/repo"

    def test_malformed_workflow_payload_returns_400(self):
        """Malformed workflow_run payloads should fail safely."""
        payload = {"action": "completed", "repository": {"full_name": "owner/repo"}}
        body = json.dumps(payload).encode()
        sig = _sign(payload, WEBHOOK_SECRET)

        client = self._get_client()
        resp = client.post(
            "/api/v1/webhook/github",
            content=body,
            headers={
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "workflow_run",
                "Content-Type": "application/json",
            },
        )

        assert resp.status_code == 400
        assert resp.json()["accepted"] is False

    def test_push_event_parses_and_accepts(self):
        """Push events should be accepted and logged."""
        payload = {
            "ref": "refs/heads/main",
            "after": "abc123def456",
            "repository": {"full_name": "owner/repo"},
            "pusher": {"name": "test-user"},
        }
        body = json.dumps(payload).encode()
        sig = _sign(payload, WEBHOOK_SECRET)

        client = self._get_client()
        resp = client.post(
            "/api/v1/webhook/github",
            content=body,
            headers={
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "push",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["accepted"] is True
        assert "Push event received" in data["message"]

    def test_ping_event_returns_ok(self):
        """Ping events from GitHub should be accepted."""
        payload = {"zen": "Keep it logically awesome", "repository": {"full_name": "owner/repo"}}
        body = json.dumps(payload).encode()
        sig = _sign(payload, WEBHOOK_SECRET)

        client = self._get_client()
        resp = client.post(
            "/api/v1/webhook/github",
            content=body,
            headers={
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "ping",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["accepted"] is True
        assert "GitHub ping event" in data["message"]


class TestPRWebhook:
    """Test PR feedback webhook."""

    def test_extract_run_id(self):
        """Should extract run ID from PR title."""
        from src.webhook.receiver import _extract_run_id_from_title
        assert _extract_run_id_from_title("🧠 NeuroCI: Fix ImportError (run #12345)") == 12345
        assert _extract_run_id_from_title("Regular PR title") == 0
        assert _extract_run_id_from_title("NeuroCI: Fix (run #999)") == 999


class TestHealthEndpoints:
    """Test health and readiness endpoints."""

    def _get_client(self):
        with patch("src.config.get_settings") as ms:
            s = MagicMock()
            s.github_webhook_secret = "test"
            s.github_allowed_repos = []
            s.log_level = "INFO"
            s.redis_url = "redis://localhost:6379/0"
            s.chroma_host = "localhost"
            s.chroma_port = 8000
            s.opa_url = "http://localhost:8181"
            s.ci_failure_store_path = "data/ci_failures.json"
            s.ci_remediation_store_path = "data/ci_remediations.json"
            s.github_remediation_enabled = False
            s.github_remediation_dry_run = True
            ms.return_value = s
            from fastapi.testclient import TestClient

            from src.main import app
            return TestClient(app)

    def test_health(self):
        """Health check should return 200."""
        client = self._get_client()
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_root(self):
        """Root should return service info."""
        client = self._get_client()
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json()["service"] == "NeuroCI"


class TestCIFailureEndpoint:
    """Test CI failure monitoring API."""

    def test_ci_failures_endpoint(self):
        from datetime import datetime

        from fastapi.testclient import TestClient

        from src.main import app
        from src.models import CIFailureAnalysis

        failure = CIFailureAnalysis(
            run_id=12345,
            repository="owner/repo",
            workflow_name="pytest",
            failed_job="unit tests",
            branch="main",
            commit_sha="abc123",
            conclusion="failure",
            failure_type="pytest failed",
            summary="pytest failed on main",
            remediation_suggestions=["Run pytest locally."],
            created_at=datetime.utcnow(),
        )

        with patch("src.ci.router.list_failure_analyses", return_value=[failure]):
            client = TestClient(app)
            resp = client.get("/api/v1/ci/failures")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["failures"][0]["run_id"] == 12345
        assert data["failures"][0]["failure_type"] == "pytest failed"

    def test_ci_remediations_endpoint(self):
        from fastapi.testclient import TestClient

        from src.main import app
        from src.models import CIRemediationRecord

        record = CIRemediationRecord(
            run_id=12345,
            repository="owner/repo",
            failure_type="dependency missing",
            status="dry_run",
            branch_name="neuroci/autofix-12345-repo-dependency-missing",
            dry_run=True,
            files_changed=["requirements.txt"],
        )

        with patch("src.ci.router.list_remediation_records", return_value=[record]):
            client = TestClient(app)
            resp = client.get("/api/v1/ci/remediations")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["remediations"][0]["status"] == "dry_run"
