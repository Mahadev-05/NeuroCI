"""Minimal GitHub API client for safe remediation pull requests."""

from __future__ import annotations

import base64
from dataclasses import dataclass

import httpx
import structlog

from src.models import CIRemediationPlan

logger = structlog.get_logger()


@dataclass(frozen=True)
class GitHubPRResult:
    """Result returned after creating a remediation pull request."""

    pr_url: str
    pr_number: int


class GitHubPRManager:
    """Create branches, commits, and pull requests using the GitHub REST API."""

    def __init__(self, token: str, api_base: str = "https://api.github.com") -> None:
        self.api_base = api_base.rstrip("/")
        self.client = httpx.Client(
            base_url=self.api_base,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "NeuroCI-AutoFix",
            },
            timeout=30.0,
            follow_redirects=True,
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> GitHubPRManager:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def get_file_content(self, repo: str, file_path: str, ref: str) -> str:
        """Read a text file from GitHub. Missing files return an empty string."""
        response = self.client.get(f"/repos/{repo}/contents/{file_path}", params={"ref": ref})
        if response.status_code == 404:
            return ""
        response.raise_for_status()
        data = response.json()
        content = data.get("content", "")
        encoding = data.get("encoding", "")
        if encoding != "base64":
            return ""
        return base64.b64decode(content).decode("utf-8")

    def create_remediation_pr(self, plan: CIRemediationPlan) -> GitHubPRResult:
        """Create a branch, write deterministic patches, and open a pull request."""
        base_sha = self._get_branch_sha(plan.repository, plan.base_branch)
        self._create_branch(plan.repository, plan.branch_name, base_sha)

        for patch in plan.patches:
            self._put_file(
                repo=plan.repository,
                file_path=patch.file_path,
                branch=plan.branch_name,
                content=patch.new_content,
                message=plan.commit_message,
            )
            logger.info(
                "ci.remediation.commit_generated",
                repo=plan.repository,
                branch=plan.branch_name,
                file_path=patch.file_path,
                run_id=plan.run_id,
            )

        pr = self._create_pull_request(plan)
        return GitHubPRResult(
            pr_url=str(pr.get("html_url", "")),
            pr_number=int(pr.get("number", 0)),
        )

    def _get_branch_sha(self, repo: str, branch: str) -> str:
        response = self.client.get(f"/repos/{repo}/git/ref/heads/{branch}")
        response.raise_for_status()
        return str(response.json()["object"]["sha"])

    def _create_branch(self, repo: str, branch: str, base_sha: str) -> None:
        response = self.client.post(
            f"/repos/{repo}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": base_sha},
        )
        if response.status_code == 422:
            raise ValueError(f"Remediation branch already exists: {branch}")
        response.raise_for_status()
        logger.info("ci.remediation.branch_created", repo=repo, branch=branch, base_sha=base_sha)

    def _put_file(
        self,
        repo: str,
        file_path: str,
        branch: str,
        content: str,
        message: str,
    ) -> None:
        current_sha = self._get_file_sha(repo, file_path, branch)
        payload = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if current_sha:
            payload["sha"] = current_sha

        response = self.client.put(f"/repos/{repo}/contents/{file_path}", json=payload)
        response.raise_for_status()

    def _get_file_sha(self, repo: str, file_path: str, ref: str) -> str:
        response = self.client.get(f"/repos/{repo}/contents/{file_path}", params={"ref": ref})
        if response.status_code == 404:
            return ""
        response.raise_for_status()
        return str(response.json().get("sha", ""))

    def _create_pull_request(self, plan: CIRemediationPlan) -> dict:
        response = self.client.post(
            f"/repos/{plan.repository}/pulls",
            json={
                "title": plan.pr_title,
                "head": plan.branch_name,
                "base": plan.base_branch,
                "body": plan.pr_body,
                "maintainer_can_modify": True,
            },
        )
        response.raise_for_status()
        data = response.json()
        logger.info(
            "ci.remediation.pr_created",
            repo=plan.repository,
            branch=plan.branch_name,
            pr_url=data.get("html_url", ""),
            pr_number=data.get("number", 0),
        )
        return data
