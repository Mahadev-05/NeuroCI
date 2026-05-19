"""
NeuroCI — Pydantic Models.

All data models for webhook payloads, agent state, patches, and API responses.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════
# Failure Categories — the 10 canonical types
# ═══════════════════════════════════════════════════════════
class FailureCategory(str, Enum):
    IMPORT_ERROR = "ImportError"
    DEPENDENCY_VERSION_CONFLICT = "DependencyVersionConflict"
    TEST_ASSERTION = "TestAssertion"
    FLAKY_TEST = "FlakyTest"
    CONFIG_MISSING = "ConfigMissing"
    TYPE_MISMATCH = "TypeMismatch"
    SYNTAX_ERROR = "SyntaxError"
    LOGIC_BUG = "LogicBug"
    AUTH_ERROR = "AuthError"
    NETWORK_TIMEOUT = "NetworkTimeout"
    UNKNOWN = "Unknown"

    @property
    def is_patchable(self) -> bool:
        """Categories where NeuroCI should attempt a code patch."""
        return self in {
            FailureCategory.IMPORT_ERROR,
            FailureCategory.DEPENDENCY_VERSION_CONFLICT,
            FailureCategory.TEST_ASSERTION,
            FailureCategory.CONFIG_MISSING,
            FailureCategory.TYPE_MISMATCH,
            FailureCategory.SYNTAX_ERROR,
            FailureCategory.LOGIC_BUG,
        }

    @property
    def is_high_risk(self) -> bool:
        """Categories that trigger multi-agent debate."""
        return self == FailureCategory.LOGIC_BUG


# ═══════════════════════════════════════════════════════════
# GitHub Webhook Payload Models
# ═══════════════════════════════════════════════════════════
class GitHubRepository(BaseModel):
    id: int
    full_name: str
    html_url: str
    default_branch: str = "main"


class GitHubWorkflowRun(BaseModel):
    id: int
    name: str
    head_branch: str
    head_sha: str
    conclusion: str | None = None
    html_url: str
    run_attempt: int = 1
    logs_url: str = ""


class GitHubWebhookPayload(BaseModel):
    """Payload from GitHub workflow_run webhook event."""
    action: str
    workflow_run: GitHubWorkflowRun
    repository: GitHubRepository


# ═══════════════════════════════════════════════════════════
# Parsed Failure Information
# ═══════════════════════════════════════════════════════════
class ParsedError(BaseModel):
    """Structured error fields extracted from CI logs."""
    file_path: str = ""
    line_number: int | None = None
    error_type: str = ""
    error_message: str = ""
    stack_trace: str = ""
    raw_log: str = ""
    failed_step: str = ""
    language: str = "python"


# ═══════════════════════════════════════════════════════════
# Agent State — flows through the entire repair pipeline
# ═══════════════════════════════════════════════════════════
class FilePatch(BaseModel):
    """A patch targeting a single file."""
    target_file: str
    unified_diff: str
    lines_changed: int = 0
    language: str = "python"


class PatchResult(BaseModel):
    """Generated patch from the LLM."""
    unified_diff: str = ""
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    reasoning: str = ""
    pr_description: str = ""
    target_file: str = ""
    lines_changed: int = 0
    patches: list[FilePatch] = Field(default_factory=list)

    @property
    def all_patches(self) -> list[FilePatch]:
        if self.patches:
            return self.patches
        if self.unified_diff and self.target_file:
            return [FilePatch(target_file=self.target_file, unified_diff=self.unified_diff, lines_changed=self.lines_changed)]
        return []


class SimilarFix(BaseModel):
    """A past failure→fix pair retrieved from ChromaDB."""
    failure_log: str
    fix_diff: str
    category: str
    outcome: str  # "success" or "rejected"
    similarity_score: float = 0.0


class RepairResult(BaseModel):
    """Final result of a repair attempt."""
    success: bool = False
    action_taken: str = ""  # "auto_pr", "slack_approval", "escalated", "skipped"
    pr_url: str = ""
    patch: PatchResult | None = None
    category: FailureCategory = FailureCategory.UNKNOWN
    error_message: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AgentState(BaseModel):
    """
    Complete state object that flows through the repair pipeline.
    Each step enriches this state as it moves through:
    webhook → log parse → classify → RAG → generate → validate → policy → PR/Slack
    """
    # ── Input (from webhook) ──
    run_id: int
    repo_full_name: str
    head_branch: str
    head_sha: str
    workflow_name: str = ""
    run_url: str = ""

    # ── Log Parsing ──
    parsed_error: ParsedError | None = None

    # ── Classification ──
    category: FailureCategory = FailureCategory.UNKNOWN

    # ── RAG ──
    similar_fixes: list[SimilarFix] = Field(default_factory=list)

    # ── Patch Generation ──
    patch: PatchResult | None = None
    file_content: str = ""  # Original file content from GitHub
    file_contents: dict[str, str] = Field(default_factory=dict)

    # ── Validation ──
    validation_passed: bool = False
    validation_errors: list[str] = Field(default_factory=list)
    retry_count: int = 0

    # ── Policy ──
    policy_allowed: bool = False
    policy_reason: str = ""

    # ── Result ──
    result: RepairResult | None = None


# ═══════════════════════════════════════════════════════════
# API Response Models
# ═══════════════════════════════════════════════════════════
class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class WebhookResponse(BaseModel):
    accepted: bool
    message: str
    run_id: int | None = None


class MetricsSnapshot(BaseModel):
    """Point-in-time metrics for API consumers."""
    total_failures_processed: int = 0
    total_fixes_attempted: int = 0
    total_fixes_merged: int = 0
    fix_accuracy_7d: float = 0.0
    avg_confidence: float = 0.0
    mttr_seconds: float = 0.0
    fixes_by_category: dict[str, int] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════
# OPA Policy Input
# ═══════════════════════════════════════════════════════════
class PolicyInput(BaseModel):
    """Input document sent to OPA for policy evaluation."""
    repo: str
    branch: str
    target_file: str
    confidence: float
    category: str
    lines_changed: int
    restricted_paths: list[str] = Field(default_factory=list)
