"""Safe deterministic remediation planning and PR orchestration."""

from __future__ import annotations

import re
from collections.abc import Callable

import structlog

from src.ci.storage import (
    has_remediation_for_run,
    save_remediation_record,
)
from src.github.pr_manager import GitHubPRManager
from src.models import (
    CIFailureAnalysis,
    CIRemediationPatch,
    CIRemediationPlan,
    CIRemediationRecord,
)

logger = structlog.get_logger()

SUPPORTED_FAILURE_TYPES = {
    "dependency missing",
    "requirements.txt mismatch",
    "import error",
    "formatting issue",
    "linting failed",
    "basic GitHub Actions YAML issue",
    "simple pytest config issue",
}


def build_branch_name(analysis: CIFailureAnalysis) -> str:
    """Build a deterministic branch name so each workflow run gets at most one PR."""
    repo_safe = _slug(analysis.repository.split("/")[-1])
    failure_safe = _slug(analysis.failure_type)
    return f"neuroci/autofix-{analysis.run_id}-{repo_safe}-{failure_safe}"[:120]


def generate_remediation_plan(
    analysis: CIFailureAnalysis,
    file_loader: Callable[[str], str] | None = None,
) -> CIRemediationPlan | None:
    """Generate a deterministic and reversible remediation plan for supported failures."""
    if analysis.failure_type not in SUPPORTED_FAILURE_TYPES:
        logger.info(
            "ci.remediation.skipped",
            run_id=analysis.run_id,
            repo=analysis.repository,
            failure_type=analysis.failure_type,
            reason="unsupported_failure_type",
        )
        return None

    if analysis.branch.startswith("neuroci/autofix"):
        logger.info(
            "ci.remediation.skipped",
            run_id=analysis.run_id,
            repo=analysis.repository,
            branch=analysis.branch,
            reason="autofix_branch_loop_prevention",
        )
        return None

    file_loader = file_loader or (lambda _path: "")
    patch = _build_patch(analysis, file_loader)
    if not patch:
        logger.info(
            "ci.remediation.skipped",
            run_id=analysis.run_id,
            repo=analysis.repository,
            failure_type=analysis.failure_type,
            reason="no_safe_deterministic_patch",
        )
        return None

    branch_name = build_branch_name(analysis)
    summary = patch.explanation
    title = f"[NeuroCI AutoFix] Fix CI failure: {analysis.failure_type}"
    body = _build_pr_body(analysis, summary, patch.file_path)

    return CIRemediationPlan(
        run_id=analysis.run_id,
        repository=analysis.repository,
        base_branch=analysis.branch,
        branch_name=branch_name,
        failure_type=analysis.failure_type,
        remediation_summary=summary,
        commit_message=f"NeuroCI AutoFix: {analysis.failure_type}",
        pr_title=title,
        pr_body=body,
        patches=[patch],
    )


def process_remediation(analysis: CIFailureAnalysis, settings) -> CIRemediationRecord:
    """Generate and optionally publish a remediation pull request."""
    if not settings.github_remediation_enabled:
        record = _record(analysis, status="skipped", reason="remediation_disabled")
        save_remediation_record(record)
        logger.info("ci.remediation.skipped", run_id=analysis.run_id, reason=record.reason)
        return record

    if has_remediation_for_run(analysis.run_id):
        record = _record(analysis, status="skipped", reason="remediation_already_attempted")
        logger.info("ci.remediation.skipped", run_id=analysis.run_id, reason=record.reason)
        return record

    if settings.github_remediation_dry_run:
        plan = generate_remediation_plan(analysis)
        if not plan:
            record = _record(analysis, status="skipped", reason="unsupported_or_unsafe_failure")
        else:
            record = _record(
                analysis,
                status="dry_run",
                branch_name=plan.branch_name,
                reason="dry_run_enabled",
                remediation_summary=plan.remediation_summary,
                files_changed=[patch.file_path for patch in plan.patches],
            )
        save_remediation_record(record)
        logger.info(
            "ci.remediation.dry_run",
            run_id=analysis.run_id,
            status=record.status,
            branch=record.branch_name,
            files_changed=record.files_changed,
        )
        return record

    if not settings.github_token:
        record = _record(analysis, status="failed", reason="missing_github_token", dry_run=False)
        save_remediation_record(record)
        logger.error("ci.remediation.failed", run_id=analysis.run_id, reason=record.reason)
        return record

    try:
        with GitHubPRManager(settings.github_token) as manager:
            plan = generate_remediation_plan(
                analysis,
                file_loader=lambda path: manager.get_file_content(
                    analysis.repository,
                    path,
                    analysis.branch,
                ),
            )
            if not plan:
                record = _record(
                    analysis,
                    status="skipped",
                    reason="unsupported_or_unsafe_failure",
                    dry_run=False,
                )
                save_remediation_record(record)
                return record

            result = manager.create_remediation_pr(plan)
    except Exception as exc:
        record = _record(analysis, status="failed", reason=str(exc), dry_run=False)
        save_remediation_record(record)
        logger.error("ci.remediation.failed", run_id=analysis.run_id, error=str(exc))
        return record

    record = _record(
        analysis,
        status="success",
        branch_name=plan.branch_name,
        pr_url=result.pr_url,
        pr_number=result.pr_number,
        dry_run=False,
        remediation_summary=plan.remediation_summary,
        files_changed=[patch.file_path for patch in plan.patches],
    )
    save_remediation_record(record)
    logger.info(
        "ci.remediation.success",
        run_id=analysis.run_id,
        repo=analysis.repository,
        branch=record.branch_name,
        pr_url=record.pr_url,
    )
    return record


def _build_patch(
    analysis: CIFailureAnalysis,
    file_loader: Callable[[str], str],
) -> CIRemediationPatch | None:
    if analysis.failure_type in {"dependency missing", "requirements.txt mismatch", "import error"}:
        package = _extract_package_name(analysis)
        if not package:
            return None
        current = file_loader("requirements.txt")
        if _has_requirement(current, package):
            return None
        new_content = _append_line(current, package)
        return CIRemediationPatch(
            file_path="requirements.txt",
            new_content=new_content,
            explanation=f"Add missing dependency `{package}` to requirements.txt.",
        )

    if analysis.failure_type in {"formatting issue", "linting failed"}:
        current = file_loader("pyproject.toml")
        if "[tool.ruff]" in current:
            return None
        new_content = _append_block(
            current,
            "\n[tool.ruff]\nline-length = 100\n\n[tool.ruff.format]\nquote-style = \"double\"\nindent-style = \"space\"\n",
        )
        return CIRemediationPatch(
            file_path="pyproject.toml",
            new_content=new_content,
            explanation="Add a minimal Ruff formatting configuration to make lint behavior explicit.",
        )

    if analysis.failure_type == "simple pytest config issue":
        current = file_loader("pyproject.toml")
        if "[tool.pytest.ini_options]" in current:
            return None
        new_content = _append_block(
            current,
            "\n[tool.pytest.ini_options]\ntestpaths = [\"tests\"]\nasyncio_mode = \"auto\"\n",
        )
        return CIRemediationPatch(
            file_path="pyproject.toml",
            new_content=new_content,
            explanation="Add minimal pytest discovery configuration for the tests directory.",
        )

    if analysis.failure_type == "basic GitHub Actions YAML issue":
        current = file_loader(".github/workflows/ci.yml")
        if "actions/setup-python" in current:
            return None
        new_content = _append_block(
            current,
            "\n# NeuroCI note: verify actions/setup-python is configured for Python projects.\n",
        )
        return CIRemediationPatch(
            file_path=".github/workflows/ci.yml",
            new_content=new_content,
            explanation="Add an explicit CI note to review Python setup in the workflow file.",
        )

    return None


def _build_pr_body(analysis: CIFailureAnalysis, remediation: str, file_path: str) -> str:
    return "\n".join(
        [
            "## NeuroCI automated remediation",
            "",
            f"Detected failure: `{analysis.failure_type}`",
            f"Workflow: `{analysis.workflow_name}`",
            f"Failed job: `{analysis.failed_job}`",
            f"Branch: `{analysis.branch}`",
            f"Commit: `{analysis.commit_sha}`",
            f"Run: {analysis.run_url or 'not provided'}",
            "",
            "## Generated remediation",
            "",
            f"- {remediation}",
            f"- File changed: `{file_path}`",
            "",
            "## Safety notice",
            "",
            "This fix is AI-generated by NeuroCI using deterministic, minimal rules.",
            "A manual review is recommended before merging.",
        ]
    )


def _record(
    analysis: CIFailureAnalysis,
    status: str,
    reason: str = "",
    branch_name: str = "",
    pr_url: str = "",
    pr_number: int | None = None,
    dry_run: bool = True,
    remediation_summary: str = "",
    files_changed: list[str] | None = None,
) -> CIRemediationRecord:
    return CIRemediationRecord(
        run_id=analysis.run_id,
        repository=analysis.repository,
        failure_type=analysis.failure_type,
        status=status,
        branch_name=branch_name,
        pr_url=pr_url,
        pr_number=pr_number,
        dry_run=dry_run,
        reason=reason,
        remediation_summary=remediation_summary,
        files_changed=files_changed or [],
    )


def _extract_package_name(analysis: CIFailureAnalysis) -> str:
    text = " ".join(
        [
            analysis.summary,
            analysis.failed_job,
            analysis.workflow_name,
            *analysis.remediation_suggestions,
        ]
    )
    patterns = [
        r"No module named ['\"]([A-Za-z0-9_.-]+)['\"]",
        r"ModuleNotFoundError:\s*No module named ['\"]([A-Za-z0-9_.-]+)['\"]",
        r"ImportError:\s*No module named ['\"]([A-Za-z0-9_.-]+)['\"]",
        r"missing dependency[:\s]+([A-Za-z0-9_.-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _normalise_package(match.group(1))
    return ""


def _normalise_package(name: str) -> str:
    return name.strip().split(".")[0].replace("_", "-").lower()


def _has_requirement(content: str, package: str) -> bool:
    package_lower = package.lower()
    for line in content.splitlines():
        clean = line.strip().lower()
        if not clean or clean.startswith("#"):
            continue
        name = re.split(r"[<>=!~\[]", clean, maxsplit=1)[0].strip()
        if name == package_lower:
            return True
    return False


def _append_line(content: str, line: str) -> str:
    if not content:
        return f"{line}\n"
    stripped = content.rstrip()
    return f"{stripped}\n{line}\n"


def _append_block(content: str, block: str) -> str:
    if not content:
        return block.lstrip()
    return f"{content.rstrip()}\n{block}"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return slug or "ci"
