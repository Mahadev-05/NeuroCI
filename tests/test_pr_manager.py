"""Tests for GitHub remediation PR payloads."""

from src.github.pr_manager import GitHubPRManager
from src.models import CIRemediationPatch, CIRemediationPlan


class _FakeResponse:
    def __init__(self, status_code: int, data: dict):
        self.status_code = status_code
        self._data = data

    def json(self) -> dict:
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict]] = []

    def post(self, path: str, json: dict) -> _FakeResponse:
        self.posts.append((path, json))
        return _FakeResponse(201, {"html_url": "https://github.com/owner/repo/pull/7", "number": 7})


def test_create_pull_request_payload():
    manager = GitHubPRManager("token")
    fake_client = _FakeClient()
    manager.client = fake_client
    plan = CIRemediationPlan(
        run_id=12345,
        repository="owner/repo",
        base_branch="main",
        branch_name="neuroci/autofix-12345-repo-dependency-missing",
        failure_type="dependency missing",
        remediation_summary="Add missing dependency `requests`.",
        commit_message="NeuroCI AutoFix: dependency missing",
        pr_title="[NeuroCI AutoFix] Fix CI failure: dependency missing",
        pr_body="AI-generated fix. Please perform manual review.",
        patches=[
            CIRemediationPatch(
                file_path="requirements.txt",
                new_content="requests\n",
                explanation="Add requests.",
            )
        ],
    )

    data = manager._create_pull_request(plan)

    assert data["number"] == 7
    assert fake_client.posts == [
        (
            "/repos/owner/repo/pulls",
            {
                "title": "[NeuroCI AutoFix] Fix CI failure: dependency missing",
                "head": "neuroci/autofix-12345-repo-dependency-missing",
                "base": "main",
                "body": "AI-generated fix. Please perform manual review.",
                "maintainer_can_modify": True,
            },
        )
    ]
