"""
NeuroCI — GitHub Client Tests.

Tests for GitHub API interactions with mocked httpx.
"""
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGitHubClient:

    @pytest.mark.asyncio
    async def test_get_file_content(self):
        """File content should be base64-decoded."""
        content = "print('hello')"
        encoded = base64.b64encode(content.encode()).decode()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"content": encoded, "encoding": "base64"}
        mock_resp.raise_for_status = MagicMock()

        with patch("src.pipeline.github_client.get_settings") as ms:
            ms.return_value = MagicMock(github_token="fake")
            from src.pipeline.github_client import GitHubClient
            client = GitHubClient()
            client._client = MagicMock()
            client._client.aclose = AsyncMock()
            client._client.get = AsyncMock(return_value=mock_resp)
            result = await client.get_file_content("o/r", "main.py")
            assert result == content
            await client.close()

    @pytest.mark.asyncio
    async def test_get_file_not_found(self):
        """404 should return None."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("src.pipeline.github_client.get_settings") as ms:
            ms.return_value = MagicMock(github_token="fake")
            from src.pipeline.github_client import GitHubClient
            client = GitHubClient()
            client._client = MagicMock()
            client._client.aclose = AsyncMock()
            client._client.get = AsyncMock(return_value=mock_resp)
            result = await client.get_file_content("o/r", "missing.py")
            assert result is None
            await client.close()

    @pytest.mark.asyncio
    async def test_create_branch(self):
        """Branch creation should call POST."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.raise_for_status = MagicMock()

        with patch("src.pipeline.github_client.get_settings") as ms:
            ms.return_value = MagicMock(github_token="fake")
            from src.pipeline.github_client import GitHubClient
            client = GitHubClient()
            client._client = MagicMock()
            client._client.aclose = AsyncMock()
            client._client.post = AsyncMock(return_value=mock_resp)
            result = await client.create_branch("o/r", "fix-branch", "abc123")
            assert result is True
            await client.close()

    @pytest.mark.asyncio
    async def test_create_branch_already_exists(self):
        """422 should return False (branch exists)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 422

        with patch("src.pipeline.github_client.get_settings") as ms:
            ms.return_value = MagicMock(github_token="fake")
            from src.pipeline.github_client import GitHubClient
            client = GitHubClient()
            client._client = MagicMock()
            client._client.aclose = AsyncMock()
            client._client.post = AsyncMock(return_value=mock_resp)
            result = await client.create_branch("o/r", "fix-branch", "abc123")
            assert result is False
            await client.close()

    @pytest.mark.asyncio
    async def test_create_pull_request(self):
        """PR creation should return PR data."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"number": 42, "html_url": "https://github.com/o/r/pull/42"}
        mock_resp.raise_for_status = MagicMock()

        with patch("src.pipeline.github_client.get_settings") as ms:
            ms.return_value = MagicMock(github_token="fake")
            from src.pipeline.github_client import GitHubClient
            client = GitHubClient()
            client._client = MagicMock()
            client._client.aclose = AsyncMock()
            client._client.post = AsyncMock(return_value=mock_resp)
            result = await client.create_pull_request("o/r", "title", "body", "head")
            assert result["number"] == 42
            await client.close()

    @pytest.mark.asyncio
    async def test_download_run_logs_not_found(self):
        """404 should return empty dict."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("src.pipeline.github_client.get_settings") as ms:
            ms.return_value = MagicMock(github_token="fake")
            from src.pipeline.github_client import GitHubClient
            client = GitHubClient()
            client._client = MagicMock()
            client._client.aclose = AsyncMock()
            client._client.get = AsyncMock(return_value=mock_resp)
            result = await client.download_run_logs("o/r", 123)
            assert result == {}
            await client.close()
