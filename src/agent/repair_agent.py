"""
NeuroCI — Main Repair Agent Orchestrator.

Orchestrates the full repair pipeline:
webhook → log parse → classify → RAG → generate/debate → validate → policy → PR/Slack

This is the brain of NeuroCI — it decides what to do at each step.
"""

from __future__ import annotations

import json
import time
from typing import Any

import redis as redis_lib
import structlog

from src.agent.classifier import classify_failure
from src.agent.debate import debate_and_select
from src.agent.patch_generator import generate_patch, retry_patch
from src.agent.validator import validate_patch
from src.config import Settings, get_settings
from src.memory.vector_store import VectorStore
from src.metrics.prometheus import (
    MTTR_HISTOGRAM,
    StageTimer,
    track_repair_attempt,
)
from src.models import AgentState, FailureCategory, RepairResult
from src.notifications.slack_bot import send_escalation, send_fix_notification, send_pr_created
from src.pipeline.github_client import GitHubClient
from src.pipeline.log_parser import extract_and_parse_logs
from src.policy.opa_client import evaluate_policy

logger = structlog.get_logger()

# Categories that should not trigger a patch attempt
NON_PATCHABLE = {FailureCategory.FLAKY_TEST, FailureCategory.AUTH_ERROR,
                 FailureCategory.NETWORK_TIMEOUT, FailureCategory.UNKNOWN}


async def run_repair_pipeline(state: AgentState) -> AgentState:
    """
    Execute the full NeuroCI repair pipeline.

    Steps:
    1. Extract and parse CI logs
    2. Classify the failure
    3. Handle non-patchable categories
    4. Retrieve similar past fixes (RAG)
    5. Fetch the erroring file from GitHub
    6. Generate patch (or debate for LogicBug)
    7. Validate the patch
    8. Evaluate OPA policy
    9. Route: auto-PR or Slack approval
    10. Update vector store (feedback loop)
    """
    settings = get_settings()
    github = GitHubClient()
    vector_store = VectorStore()
    pipeline_start = time.monotonic()

    try:
        # ── Step 1: Extract and parse logs ──
        with StageTimer("log_extraction"):
            logger.info("repair.step.1_log_extraction", run_id=state.run_id)
            state = await extract_and_parse_logs(state)

        parsed_error = state.parsed_error
        if not parsed_error or not parsed_error.raw_log:
            state.result = RepairResult(
                success=False, action_taken="skipped",
                error_message="Could not retrieve CI logs",
                category=state.category,
            )
            return state

        # ── Step 1b: Deduplication by error signature ──
        import hashlib
        error_hash = hashlib.md5(parsed_error.raw_log.encode("utf-8")).hexdigest()
        logger.info("repair.check_signature", run_id=state.run_id, error_hash=error_hash)

        try:
            r = redis_lib.from_url(settings.redis_url)  # type: ignore[no-untyped-call]
            dup_data_raw = r.get(f"neuroci:signature:{error_hash}")
            if dup_data_raw:
                dup_data = json.loads(dup_data_raw)
                pr_number = dup_data.get("pr_number")
                pr_url = dup_data.get("pr_url")
                logger.info("repair.signature_duplicate", run_id=state.run_id, error_hash=error_hash, pr_number=pr_number)

                # Post comment to the existing PR
                comment_body = (
                    f"⚠️ **NeuroCI Note**: The same error signature was detected again in a new workflow run.\n"
                    f"- **Failing Run**: [{state.run_id}]({state.run_url})\n"
                    f"- **Branch**: `{state.head_branch}`\n"
                    f"- **SHA**: `{state.head_sha[:8]}`"
                )
                try:
                    await github.create_issue_comment(state.repo_full_name, pr_number, comment_body)
                    logger.info("repair.duplicate_comment_posted", run_id=state.run_id, pr_number=pr_number)
                except Exception as comment_err:
                    logger.warning("repair.duplicate_comment_failed", error=str(comment_err))

                state.result = RepairResult(
                    success=True,
                    action_taken="skipped",
                    error_message=f"Duplicate error signature (commented on PR #{pr_number})",
                    category=state.category,
                )
                r.close()
                return state
            r.close()
        except Exception as redis_err:
            logger.warning("repair.redis_signature_check_failed", error=str(redis_err))

        # ── Step 2: Classify failure ──
        with StageTimer("classification"):
            logger.info("repair.step.2_classification", run_id=state.run_id)
            state = await classify_failure(state)

        # ── Step 3: Handle non-patchable categories ──
        if state.category in NON_PATCHABLE:
            logger.info("repair.non_patchable", run_id=state.run_id,
                        category=state.category.value)

            if state.category == FailureCategory.FLAKY_TEST:
                action = "flaky_test_requeue"
            else:
                action = "slack_alert_only"

            await send_escalation(state, reason=f"Non-patchable: {state.category.value}")

            state.result = RepairResult(
                success=False, action_taken=action,
                category=state.category,
                error_message=f"Category {state.category.value} is not auto-patchable",
            )
            track_repair_attempt(state)
            return state

        # ── Step 4: RAG — retrieve similar past fixes ──
        with StageTimer("rag_lookup"):
            logger.info("repair.step.4_rag_lookup", run_id=state.run_id)
            state.similar_fixes = await vector_store.find_similar(
                parsed_error.raw_log[:2000], top_k=3
            )

        # ── Step 5: Fetch erroring file from GitHub ──
        if parsed_error.file_path:
            with StageTimer("fetch_file"):
                logger.info("repair.step.5_fetch_file", run_id=state.run_id,
                            file=parsed_error.file_path)
                state.file_content = await github.get_file_content(
                    state.repo_full_name,
                    parsed_error.file_path,
                    ref=state.head_sha,
                ) or ""

        # ── Step 6: Generate patch ──
        with StageTimer("patch_generation"):
            if state.category.is_high_risk:
                logger.info("repair.step.6_debate", run_id=state.run_id)
                state = await debate_and_select(state)
            else:
                logger.info("repair.step.6_patch_gen", run_id=state.run_id)
                state = await generate_patch(state)

        if not state.patch or not state.patch.unified_diff:
            state.result = RepairResult(
                success=False, action_taken="escalated",
                category=state.category,
                error_message="LLM failed to generate a patch",
            )
            await send_escalation(state, reason="Patch generation failed")
            track_repair_attempt(state)
            return state

        # ── Step 7: Validate patch ──
        with StageTimer("validation"):
            logger.info("repair.step.7_validation", run_id=state.run_id)
            state = await validate_patch(state)

            if not state.validation_passed:
                # Retry once with error feedback
                if state.retry_count < 1:
                    state.retry_count += 1
                    logger.info("repair.step.7_retry", run_id=state.run_id)

                    # Safely extract previous diff
                    current_patch = state.patch
                    prev_diff = current_patch.unified_diff if current_patch else ""

                    state = await retry_patch(
                        state,
                        validation_error="\n".join(state.validation_errors),
                        previous_diff=prev_diff,
                    )
                    state = await validate_patch(state)

            if not state.validation_passed:
                state.result = RepairResult(
                    success=False, action_taken="escalated",
                    category=state.category, patch=state.patch,
                    error_message=f"Validation failed: {state.validation_errors}",
                )
                await send_escalation(state, reason="Patch validation failed after retry")
                track_repair_attempt(state)
                return state

        # ── Step 8: OPA policy evaluation ──
        with StageTimer("policy_evaluation"):
            logger.info("repair.step.8_policy", run_id=state.run_id)
            state = await evaluate_policy(state)

        if not state.policy_allowed:
            state.result = RepairResult(
                success=False, action_taken="escalated",
                category=state.category, patch=state.patch,
                error_message=f"Policy blocked: {state.policy_reason}",
            )
            await send_escalation(state, reason=f"Policy: {state.policy_reason}")
            track_repair_attempt(state)
            return state

        # ── Step 9: Route — auto-PR or Slack approval ──
        current_patch = state.patch
        if not current_patch:
            raise ValueError("Patch is missing")

        threshold = settings.neuroci_confidence_threshold
        if settings.dry_run:
            logger.info("repair.step.9_dry_run", run_id=state.run_id)
            await send_fix_notification(state, dry_run=True)
            state.result = RepairResult(
                success=True, action_taken="slack_approval",
                category=state.category, patch=state.patch,
            )
        elif current_patch.confidence >= threshold:
            with StageTimer("auto_pr"):
                logger.info("repair.step.9_auto_pr", run_id=state.run_id,
                            confidence=current_patch.confidence)
                pr_data = await _create_fix_pr(github, state)
                pr_url = pr_data.get("html_url", "")
                state.result = RepairResult(
                    success=True, action_taken="auto_pr",
                    category=state.category, patch=state.patch, pr_url=pr_url,
                )
                # Notify Slack about the auto-created PR
                await send_pr_created(state, pr_url)
        else:
            logger.info("repair.step.9_slack_approval", run_id=state.run_id,
                        confidence=current_patch.confidence)
            # Cache state in Redis for Slack "Apply Fix" button
            await _cache_state_to_redis(state, settings)
            await send_fix_notification(state)
            state.result = RepairResult(
                success=True, action_taken="slack_approval",
                category=state.category, patch=state.patch,
            )

        # ── Step 10: Feedback loop — update vector store + metrics ──
        with StageTimer("feedback_loop"):
            logger.info("repair.step.10_feedback", run_id=state.run_id)
            track_repair_attempt(state)

            # Store the fix attempt in ChromaDB for RAG learning
            if current_patch and parsed_error:
                outcome = "auto_pr" if state.result and state.result.action_taken == "auto_pr" else "pending"
                await vector_store.store_fix(
                    failure_log=parsed_error.raw_log[:4000],
                    fix_diff=current_patch.unified_diff[:4000],
                    category=state.category.value,
                    outcome=outcome,
                    repo=state.repo_full_name,
                    run_id=state.run_id,
                )

        # ── Track MTTR ──
        mttr = time.monotonic() - pipeline_start
        MTTR_HISTOGRAM.observe(mttr)
        logger.info("repair.mttr", run_id=state.run_id, mttr_seconds=f"{mttr:.2f}")

    except Exception as e:
        logger.error("repair.pipeline_error", run_id=state.run_id, error=str(e))
        state.result = RepairResult(
            success=False, action_taken="error",
            category=state.category,
            error_message=str(e),
        )
    finally:
        await github.close()

    return state


async def _cache_state_to_redis(state: AgentState, settings: Settings) -> None:
    """Cache agent state in Redis for the Slack 'Apply Fix' flow."""
    try:
        r = redis_lib.from_url(settings.redis_url)  # type: ignore[no-untyped-call]
        state_json = json.dumps(state.model_dump(), default=str)
        # Cache for 24 hours
        r.setex(f"neuroci:state:{state.run_id}", 86400, state_json)
        r.close()
        logger.info("repair.state_cached", run_id=state.run_id)
    except Exception as e:
        logger.warning("repair.state_cache_failed", error=str(e), run_id=state.run_id)


async def _create_fix_pr(github: GitHubClient, state: AgentState) -> dict[str, Any]:
    """Create a fix branch and pull request on GitHub."""
    branch_name = f"neuroci/fix-{state.run_id}"

    # Create branch from the failing commit
    await github.create_branch(state.repo_full_name, branch_name, state.head_sha)

    # Apply the patches by updating the files
    if state.patch:
        from src.agent.validator import apply_unified_diff
        for file_patch in state.patch.all_patches:
            target_file = file_patch.target_file
            content = state.file_contents.get(target_file)
            if content is None:
                content = await github.get_file_content(
                    state.repo_full_name,
                    target_file,
                    ref=state.head_sha
                ) or ""
                state.file_contents[target_file] = content

            patched = apply_unified_diff(content, file_patch.unified_diff)
            if patched:
                await github.update_file(
                    repo=state.repo_full_name,
                    file_path=target_file,
                    content=patched,
                    message=f"fix: {state.category.value} — auto-repair by NeuroCI\n\n{state.patch.reasoning[:200]}",
                    branch=branch_name,
                )

    # Build PR body
    pr_body = _build_pr_body(state)

    # Create PR
    pr_data = await github.create_pull_request(
        repo=state.repo_full_name,
        title=f"🧠 NeuroCI: Fix {state.category.value} (run #{state.run_id})",
        body=pr_body,
        head=branch_name,
        base=state.head_branch,
    )

    # Cache error signature in Redis if raw log exists
    parsed_error = state.parsed_error
    if parsed_error and parsed_error.raw_log:
        import hashlib
        error_hash = hashlib.md5(parsed_error.raw_log.encode("utf-8")).hexdigest()
        try:
            settings = get_settings()
            r = redis_lib.from_url(settings.redis_url)  # type: ignore[no-untyped-call]
            val = json.dumps({
                "pr_number": pr_data.get("number"),
                "pr_url": pr_data.get("html_url"),
                "run_id": state.run_id
            })
            # 1 hour TTL
            r.setex(f"neuroci:signature:{error_hash}", 3600, val)
            r.close()
            logger.info("repair.cached_signature", run_id=state.run_id, error_hash=error_hash)
        except Exception as cache_err:
            logger.warning("repair.cache_signature_failed", error=str(cache_err))

    return pr_data


def _build_pr_body(state: AgentState) -> str:
    """Build a rich PR description."""
    patch = state.patch
    pe = state.parsed_error
    conf = patch.confidence if patch else 0
    conf_bar = "█" * int(conf * 10) + "░" * (10 - int(conf * 10))

    files_changed_list = []
    total_lines = 0
    if patch:
        for fp in patch.all_patches:
            files_changed_list.append(f"`{fp.target_file}` ({fp.lines_changed} lines)")
            total_lines += fp.lines_changed
    files_changed_str = ", ".join(files_changed_list) or "N/A"

    return f"""## 🧠 NeuroCI Auto-Repair

**Failure Category:** `{state.category.value}`
**Confidence:** {conf:.0%} [{conf_bar}]
**Failed Run:** [{state.run_id}]({state.run_url})
**Target Files:** {files_changed_str}
**Total Lines Changed:** {total_lines}

---

### Root Cause Analysis
{patch.pr_description if patch else 'N/A'}

### Reasoning Trace
{patch.reasoning if patch else 'N/A'}

### Error Details
- **Type:** `{pe.error_type if pe else 'N/A'}`
- **Message:** {pe.error_message if pe else 'N/A'}
- **File:** `{pe.file_path if pe else 'N/A'}`
- **Line:** {pe.line_number if pe else 'N/A'}

---
*Generated by [NeuroCI](https://github.com/neuroci) — The Self-Healing Pipeline*
"""
