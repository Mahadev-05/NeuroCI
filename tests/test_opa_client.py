"""
NeuroCI — OPA Client Tests.

Tests for OPA policy evaluation and local fallback logic.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models import AgentState, FailureCategory, PatchResult
from src.policy.opa_client import _local_policy_check, evaluate_policy


def _make_state(
    confidence: float = 0.90,
    target_file: str = "src/main.py",
    lines_changed: int = 5,
    branch: str = "feature/fix",
    category: FailureCategory = FailureCategory.IMPORT_ERROR,
) -> AgentState:
    return AgentState(
        run_id=100,
        repo_full_name="owner/repo",
        head_branch=branch,
        head_sha="abc123",
        category=category,
        patch=PatchResult(
            unified_diff="- old\n+ new",
            confidence=confidence,
            target_file=target_file,
            lines_changed=lines_changed,
        ),
    )


class TestLocalPolicyCheck:
    """Test local fallback policy evaluation."""

    def test_allowed_normal_patch(self):
        """Normal patch should be allowed."""
        state = _make_state()
        settings = MagicMock()
        settings.neuroci_max_patch_lines = 20
        settings.is_path_restricted.return_value = False

        result = _local_policy_check(state, settings)
        assert result.policy_allowed is True
        assert result.policy_reason == ""

    def test_restricted_path_blocked(self):
        """Restricted path should be blocked."""
        state = _make_state(target_file="terraform/main.tf")
        settings = MagicMock()
        settings.neuroci_max_patch_lines = 20
        settings.is_path_restricted.return_value = True

        result = _local_policy_check(state, settings)
        assert result.policy_allowed is False
        assert "Restricted path" in result.policy_reason

    def test_main_branch_low_confidence_blocked(self):
        """Main branch with low confidence should be blocked."""
        state = _make_state(confidence=0.88, branch="main")
        settings = MagicMock()
        settings.neuroci_max_patch_lines = 20
        settings.is_path_restricted.return_value = False

        result = _local_policy_check(state, settings)
        assert result.policy_allowed is False
        assert "0.92" in result.policy_reason

    def test_main_branch_high_confidence_allowed(self):
        """Main branch with high confidence should be allowed."""
        state = _make_state(confidence=0.95, branch="main")
        settings = MagicMock()
        settings.neuroci_max_patch_lines = 20
        settings.is_path_restricted.return_value = False

        result = _local_policy_check(state, settings)
        assert result.policy_allowed is True

    def test_excessive_patch_blocked(self):
        """Patch with too many lines should be blocked."""
        state = _make_state(lines_changed=25)
        settings = MagicMock()
        settings.neuroci_max_patch_lines = 20
        settings.is_path_restricted.return_value = False

        result = _local_policy_check(state, settings)
        assert result.policy_allowed is False
        assert "too large" in result.policy_reason.lower() or "25 lines" in result.policy_reason

    def test_multiple_violations(self):
        """Multiple policy violations should all be reported."""
        state = _make_state(confidence=0.80, lines_changed=25, branch="main",
                            target_file="secrets.py")
        settings = MagicMock()
        settings.neuroci_max_patch_lines = 20
        settings.is_path_restricted.return_value = True

        result = _local_policy_check(state, settings)
        assert result.policy_allowed is False
        # Should have multiple reasons joined by ";"
        assert ";" in result.policy_reason


class TestEvaluatePolicy:
    """Test OPA policy evaluation with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_opa_allows(self):
        """OPA returning true should allow the patch."""
        state = _make_state()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": True}
        mock_response.raise_for_status = MagicMock()

        with patch("src.policy.opa_client.get_settings") as mock_settings:
            settings = MagicMock()
            settings.opa_url = "http://localhost:8181"
            settings.opa_policy_path = "v1/data/neuroci/allow"
            settings.neuroci_restricted_paths = ["infra/", "terraform/"]
            mock_settings.return_value = settings

            with patch("httpx.AsyncClient") as mock_client:
                client_instance = AsyncMock()
                client_instance.post = AsyncMock(return_value=mock_response)
                client_instance.__aenter__ = AsyncMock(return_value=client_instance)
                client_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = client_instance

                result = await evaluate_policy(state)
                assert result.policy_allowed is True

    @pytest.mark.asyncio
    async def test_opa_denies(self):
        """OPA returning false should deny the patch."""
        state = _make_state()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": False}
        mock_response.raise_for_status = MagicMock()

        with patch("src.policy.opa_client.get_settings") as mock_settings:
            settings = MagicMock()
            settings.opa_url = "http://localhost:8181"
            settings.opa_policy_path = "v1/data/neuroci/allow"
            settings.neuroci_restricted_paths = []
            mock_settings.return_value = settings

            with patch("httpx.AsyncClient") as mock_client:
                client_instance = AsyncMock()
                client_instance.post = AsyncMock(return_value=mock_response)
                client_instance.__aenter__ = AsyncMock(return_value=client_instance)
                client_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = client_instance

                result = await evaluate_policy(state)
                assert result.policy_allowed is False

    @pytest.mark.asyncio
    async def test_opa_unavailable_falls_back_to_local(self):
        """OPA connection failure should use local fallback."""
        state = _make_state()

        with patch("src.policy.opa_client.get_settings") as mock_settings:
            settings = MagicMock()
            settings.opa_url = "http://localhost:8181"
            settings.opa_policy_path = "v1/data/neuroci/allow"
            settings.neuroci_restricted_paths = []
            settings.neuroci_max_patch_lines = 20
            settings.is_path_restricted.return_value = False
            mock_settings.return_value = settings

            with patch("httpx.AsyncClient") as mock_client:
                client_instance = AsyncMock()
                client_instance.post = AsyncMock(side_effect=Exception("Connection refused"))
                client_instance.__aenter__ = AsyncMock(return_value=client_instance)
                client_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = client_instance

                result = await evaluate_policy(state)
                # Should use local fallback and still work
                assert result.policy_allowed is True

    @pytest.mark.asyncio
    async def test_no_patch_denied(self):
        """No patch should be denied by policy."""
        state = AgentState(
            run_id=100,
            repo_full_name="owner/repo",
            head_branch="main",
            head_sha="abc123",
        )
        result = await evaluate_policy(state)
        assert result.policy_allowed is False
        assert "No patch" in result.policy_reason
