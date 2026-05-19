"""
NeuroCI — GitHub API Client.

Handles all interactions with the GitHub REST API v3:
- Downloading workflow run logs
- Reading file content from repos
- Creating branches, commits, and pull requests
"""

from __future__ import annotations

import base64
import io
import zipfile
from typing import Any

import httpx
import structlog

from src.config import get_settings

logger = structlog.get_logger()


class GitHubClient:
    """Async GitHub REST API client."""

    BASE_URL = "https://api.github.com"

    def __init__(self) -> None:
        settings = get_settings()
        self._headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"Bearer {settings.github_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._client = httpx.AsyncClient(
            headers=self._headers,
            timeout=30.0,
            follow_redirects=True,
        )

    async def close(self) -> None:
        await self._client.aclose()

    # ═══════════════════════════════════════════════════════
    # Log Retrieval
    # ═══════════════════════════════════════════════════════
    async def download_run_logs(self, repo: str, run_id: int) -> dict[str, str]:
        """
        Download and extract workflow run logs from GitHub.

        Returns a dict mapping step name → log content.
        GitHub serves logs as a zip file containing one text file per step.
        """
        url = f"{self.BASE_URL}/repos/{repo}/actions/runs/{run_id}/logs"
        logger.info("github.download_logs", repo=repo, run_id=run_id)

        response = await self._client.get(url)

        if response.status_code == 404:
            logger.warning("github.logs_not_found", repo=repo, run_id=run_id)
            return {}

        response.raise_for_status()

        # Extract zip in memory
        logs: dict[str, str] = {}
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            for name in zf.namelist():
                if name.endswith(".txt"):
                    step_name = name.rsplit("/", 1)[-1].replace(".txt", "")
                    content = zf.read(name).decode("utf-8", errors="replace")
                    logs[step_name] = content

        logger.info("github.logs_extracted", repo=repo, steps=len(logs))
        return logs

    # ═══════════════════════════════════════════════════════
    # File Content
    # ═══════════════════════════════════════════════════════
    async def get_file_content(
        self, repo: str, file_path: str, ref: str = "main"
    ) -> str | None:
        """
        Fetch file content from a repository at a specific ref (branch/SHA).
        Returns the decoded file content, or None if the file doesn't exist.
        """
        url = f"{self.BASE_URL}/repos/{repo}/contents/{file_path}"
        params = {"ref": ref}

        response = await self._client.get(url, params=params)

        if response.status_code == 404:
            logger.warning("github.file_not_found", repo=repo, path=file_path, ref=ref)
            return None

        response.raise_for_status()
        data = response.json()

        if data.get("encoding") == "base64":
            content = base64.b64decode(data["content"]).decode("utf-8")
        else:
            content = data.get("content", "")

        logger.info("github.file_fetched", repo=repo, path=file_path, size=len(content))
        return content

    # ═══════════════════════════════════════════════════════
    # Branch Management
    # ═══════════════════════════════════════════════════════
    async def create_branch(self, repo: str, branch_name: str, from_sha: str) -> bool:
        """Create a new branch from a specific commit SHA."""
        url = f"{self.BASE_URL}/repos/{repo}/git/refs"
        data = {
            "ref": f"refs/heads/{branch_name}",
            "sha": from_sha,
        }

        response = await self._client.post(url, json=data)

        if response.status_code == 422:
            logger.warning("github.branch_exists", branch=branch_name)
            return False

        response.raise_for_status()
        logger.info("github.branch_created", repo=repo, branch=branch_name)
        return True

    # ═══════════════════════════════════════════════════════
    # File Update (Commit)
    # ═══════════════════════════════════════════════════════
    async def update_file(
        self,
        repo: str,
        file_path: str,
        content: str,
        message: str,
        branch: str,
    ) -> dict[str, Any]:
        """
        Create or update a file in a repository.
        Returns the commit data from GitHub's response.
        """
        # First, get the current file SHA (needed for updates)
        url = f"{self.BASE_URL}/repos/{repo}/contents/{file_path}"
        params = {"ref": branch}
        get_response = await self._client.get(url, params=params)

        file_sha = None
        if get_response.status_code == 200:
            file_sha = get_response.json().get("sha")

        # Now update/create the file
        data: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
            "branch": branch,
        }
        if file_sha:
            data["sha"] = file_sha

        response = await self._client.put(url, json=data)
        response.raise_for_status()

        logger.info("github.file_updated", repo=repo, path=file_path, branch=branch)
        return response.json()

    # ═══════════════════════════════════════════════════════
    # Pull Request
    # ═══════════════════════════════════════════════════════
    async def create_pull_request(
        self,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> dict[str, Any]:
        """
        Create a pull request.
        Returns the PR data including html_url.
        """
        url = f"{self.BASE_URL}/repos/{repo}/pulls"
        data = {
            "title": title,
            "body": body,
            "head": head,
            "base": base,
        }

        response = await self._client.post(url, json=data)
        response.raise_for_status()

        pr_data = response.json()
        logger.info(
            "github.pr_created",
            repo=repo,
            pr_number=pr_data["number"],
            pr_url=pr_data["html_url"],
        )
        return pr_data

    # ═══════════════════════════════════════════════════════
    # Workflow Runs
    # ═══════════════════════════════════════════════════════
    async def get_workflow_run(self, repo: str, run_id: int) -> dict[str, Any]:
        """Get details of a specific workflow run."""
        url = f"{self.BASE_URL}/repos/{repo}/actions/runs/{run_id}"
        response = await self._client.get(url)
        response.raise_for_status()
        return response.json()

    async def get_workflow_jobs(self, repo: str, run_id: int) -> list[dict[str, Any]]:
        """Get all jobs for a workflow run — useful for finding the failed step."""
        url = f"{self.BASE_URL}/repos/{repo}/actions/runs/{run_id}/jobs"
        response = await self._client.get(url)
        response.raise_for_status()
        return response.json().get("jobs", [])

    async def create_issue_comment(self, repo: str, issue_number: int, body: str) -> dict[str, Any]:
        """Post a comment to a PR or issue."""
        url = f"{self.BASE_URL}/repos/{repo}/issues/{issue_number}/comments"
        data = {"body": body}
        response = await self._client.post(url, json=data)
        response.raise_for_status()
        return response.json()
