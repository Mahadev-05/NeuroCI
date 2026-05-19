"""
NeuroCI — Slack Bot Tests.

Tests for Slack notification functions with mocked SDK.
"""
from unittest.mock import MagicMock, patch

import pytest

from src.models import AgentState, FailureCategory, ParsedError, PatchResult


def _make_state() -> AgentState:
    return AgentState(
        run_id=100, repo_full_name="o/r", head_branch="main", head_sha="abc",
        category=FailureCategory.IMPORT_ERROR, run_url="https://example.com",
        parsed_error=ParsedError(
            error_type="ModuleNotFoundError",
            error_message="No module named 'foo'",
        ),
        patch=PatchResult(
            unified_diff="- old\n+ new",
            confidence=0.88,
            target_file="src/main.py",
            lines_changed=2,
        ),
    )


class TestSlackBot:

    @pytest.mark.asyncio
    async def test_send_fix_not_configured(self):
        """No Slack token should skip silently."""
        with patch("src.notifications.slack_bot.get_settings") as ms:
            ms.return_value = MagicMock(slack_bot_token="")
            from src.notifications.slack_bot import send_fix_notification
            await send_fix_notification(_make_state())  # Should not raise

    @pytest.mark.asyncio
    async def test_send_fix_notification(self):
        """Should call chat_postMessage with blocks."""
        mock_client = MagicMock()
        with patch("src.notifications.slack_bot._get_slack_client", return_value=mock_client):
            with patch("src.notifications.slack_bot.get_settings") as ms:
                ms.return_value = MagicMock(slack_channel="#test")
                from src.notifications.slack_bot import send_fix_notification
                await send_fix_notification(_make_state())
                mock_client.chat_postMessage.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_escalation(self):
        """Should send escalation message."""
        mock_client = MagicMock()
        with patch("src.notifications.slack_bot._get_slack_client", return_value=mock_client):
            with patch("src.notifications.slack_bot.get_settings") as ms:
                ms.return_value = MagicMock(slack_channel="#test")
                from src.notifications.slack_bot import send_escalation
                await send_escalation(_make_state(), "test reason")
                mock_client.chat_postMessage.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_pr_created(self):
        """Should send PR notification."""
        mock_client = MagicMock()
        with patch("src.notifications.slack_bot._get_slack_client", return_value=mock_client):
            with patch("src.notifications.slack_bot.get_settings") as ms:
                ms.return_value = MagicMock(slack_channel="#test")
                from src.notifications.slack_bot import send_pr_created
                await send_pr_created(_make_state(), "https://github.com/o/r/pull/1")
                mock_client.chat_postMessage.assert_called_once()

    def test_confidence_bar(self):
        """Confidence bar should show correct fill level."""
        from src.notifications.slack_bot import _confidence_bar
        assert _confidence_bar(1.0) == "██████████"
        assert _confidence_bar(0.5) == "█████░░░░░"
        assert _confidence_bar(0.0) == "░░░░░░░░░░"
