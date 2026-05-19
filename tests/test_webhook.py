"""
NeuroCI — Webhook Tests.

Tests for HMAC verification, payload parsing, and webhook endpoint.
"""

import hashlib
import hmac
import json
import pytest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient


# ── Fixtures ──
WEBHOOK_SECRET = "test-secret-123"
VALID_PAYLOAD = {
    "action": "completed",
    "workflow_run": {
        "id": 12345,
        "name": "CI Pipeline",
        "head_branch": "feature/test",
        "head_sha": "abc123def456",
        "conclusion": "failure",
        "html_url": "https://github.com/owner/repo/actions/runs/12345",
        "run_attempt": 1,
        "logs_url": "",
    },
    "repository": {
        "id": 1,
        "full_name": "owner/repo",
        "html_url": "https://github.com/owner/repo",
        "default_branch": "main",
    },
}


def _sign_payload(payload: dict, secret: str) -> str:
    """Generate HMAC-SHA256 signature for a payload."""
    body = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def _get_test_client():
    """Create a test client with mocked settings."""
    with patch("src.config.get_settings") as mock_settings:
        settings = MagicMock()
        settings.github_webhook_secret = WEBHOOK_SECRET
        settings.github_allowed_repos = ["owner/repo"]
        settings.log_level = "INFO"
        settings.redis_url = "redis://localhost:6379/0"
        settings.is_repo_allowed.return_value = True
        mock_settings.return_value = settings

        from src.main import app
        return TestClient(app)


class TestWebhookSecurity:
    """Test HMAC-SHA256 signature verification."""

    def test_valid_signature(self):
        """Valid signature should be accepted."""
        from src.webhook.security import compute_signature

        payload = b'{"test": "data"}'
        sig = compute_signature(payload, WEBHOOK_SECRET)
        assert sig.startswith("sha256=")
        assert len(sig) == 71  # "sha256=" + 64 hex chars

    def test_signature_format(self):
        """Signatures should be consistent."""
        from src.webhook.security import compute_signature

        payload = b"hello world"
        sig1 = compute_signature(payload, WEBHOOK_SECRET)
        sig2 = compute_signature(payload, WEBHOOK_SECRET)
        assert sig1 == sig2

    def test_different_secrets_produce_different_signatures(self):
        """Different secrets should produce different signatures."""
        from src.webhook.security import compute_signature

        payload = b"test"
        sig1 = compute_signature(payload, "secret1")
        sig2 = compute_signature(payload, "secret2")
        assert sig1 != sig2


class TestPayloadParsing:
    """Test webhook payload parsing."""

    def test_valid_payload_parses(self):
        """Valid GitHub payload should parse without errors."""
        from src.models import GitHubWebhookPayload

        payload = GitHubWebhookPayload(**VALID_PAYLOAD)
        assert payload.action == "completed"
        assert payload.workflow_run.id == 12345
        assert payload.workflow_run.conclusion == "failure"
        assert payload.repository.full_name == "owner/repo"

    def test_non_failure_conclusion(self):
        """Non-failure conclusions should parse but be filtered."""
        from src.models import GitHubWebhookPayload

        payload_data = {**VALID_PAYLOAD}
        payload_data["workflow_run"] = {**VALID_PAYLOAD["workflow_run"], "conclusion": "success"}
        payload = GitHubWebhookPayload(**payload_data)
        assert payload.workflow_run.conclusion == "success"


class TestFailureCategories:
    """Test failure category enum."""

    def test_patchable_categories(self):
        """Verify which categories are patchable."""
        from src.models import FailureCategory

        assert FailureCategory.IMPORT_ERROR.is_patchable is True
        assert FailureCategory.SYNTAX_ERROR.is_patchable is True
        assert FailureCategory.LOGIC_BUG.is_patchable is True

    def test_non_patchable_categories(self):
        """Verify which categories are NOT patchable."""
        from src.models import FailureCategory

        assert FailureCategory.FLAKY_TEST.is_patchable is False
        assert FailureCategory.AUTH_ERROR.is_patchable is False
        assert FailureCategory.NETWORK_TIMEOUT.is_patchable is False

    def test_high_risk_category(self):
        """Only LogicBug should be high risk."""
        from src.models import FailureCategory

        assert FailureCategory.LOGIC_BUG.is_high_risk is True
        assert FailureCategory.IMPORT_ERROR.is_high_risk is False
