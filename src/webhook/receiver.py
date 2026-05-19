"""
NeuroCI — Webhook Receiver.

FastAPI router that receives GitHub webhook events,
validates them, and dispatches repair tasks to the Celery queue.

Handles:
- workflow_run events (CI failure detection)
- pull_request events (feedback loop — learning from PR outcomes)
- Slack interactive message callbacks
"""

from __future__ import annotations

import json

import redis as redis_lib
import structlog
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from src.config import get_settings
from src.metrics.prometheus import track_webhook
from src.models import (
    AgentState,
    GitHubWebhookPayload,
    WebhookResponse,
)
from src.webhook.security import verify_github_signature

logger = structlog.get_logger()
router = APIRouter()


def _get_redis() -> redis_lib.Redis | None:
    """Get a Redis client, returning None if unavailable."""
    try:
        settings = get_settings()
        r = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
        r.ping()
        return r
    except Exception:
        return None


def _is_duplicate(run_id: int) -> bool:
    """Check if a run_id has already been processed (Redis-based dedup)."""
    r = _get_redis()
    if not r:
        return False
    try:
        key = f"neuroci:processed:{run_id}"
        # Set with NX (only if not exists) and 24h expiry
        was_set = r.set(key, "1", nx=True, ex=86400)
        r.close()
        return not was_set  # If was_set is False, key already existed → duplicate
    except Exception:
        return False


@router.post(
    "/webhook/github",
    response_model=WebhookResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive GitHub webhook events",
)
async def receive_webhook(request: Request) -> WebhookResponse | JSONResponse:
    """
    GitHub webhook endpoint for workflow_run and pull_request events.

    Flow:
    1. Verify HMAC-SHA256 signature
    2. Detect event type from header
    3. Route to appropriate handler
    """
    settings = get_settings()

    # ── Step 1: Verify signature ──
    body = await verify_github_signature(request)

    # ── Step 2: Detect event type ──
    event_type = request.headers.get("X-GitHub-Event", "")

    # ── Step 3: Parse payload ──
    try:
        raw = json.loads(body)
    except Exception as e:
        logger.error("webhook.parse_error", error=str(e))
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"accepted": False, "message": f"Invalid JSON: {e}", "run_id": None},
        )

    # ── Route by event type ──
    if event_type == "pull_request":
        return await _handle_pull_request_event(raw)
    else:
        return await _handle_workflow_run_event(raw, settings)


async def _handle_workflow_run_event(
    raw: dict, settings
) -> WebhookResponse | JSONResponse:
    """Handle workflow_run webhook events — CI failure detection."""
    try:
        payload = GitHubWebhookPayload(**raw)
    except Exception as e:
        logger.error("webhook.parse_error", error=str(e))
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"accepted": False, "message": f"Invalid payload: {e}", "run_id": None},
        )

    run = payload.workflow_run
    repo = payload.repository

    # Track webhook metrics
    track_webhook(
        action=payload.action,
        conclusion=run.conclusion or "unknown",
    )

    # ── Filter — only completed events ──
    if payload.action != "completed":
        logger.debug("webhook.skipped", reason="action_not_completed", action=payload.action)
        return WebhookResponse(
            accepted=False,
            message=f"Ignoring action: {payload.action}",
            run_id=run.id,
        )

    # ── Step 11: Re-run verification — check if this is a post-fix result ──
    if run.conclusion == "success":
        verification = _check_pending_verification(repo.full_name, run.head_branch)
        if verification:
            return await _handle_verification_success(verification, run)
        # Normal success — nothing to do
        logger.debug("webhook.skipped", reason="success_no_pending_fix", run_id=run.id)
        return WebhookResponse(
            accepted=False,
            message=f"Ignoring conclusion: {run.conclusion}",
            run_id=run.id,
        )

    if run.conclusion != "failure":
        logger.debug(
            "webhook.skipped",
            reason="not_failure",
            conclusion=run.conclusion,
            run_id=run.id,
        )
        return WebhookResponse(
            accepted=False,
            message=f"Ignoring conclusion: {run.conclusion}",
            run_id=run.id,
        )

    # ── Check if this is a SECOND failure after a NeuroCI fix ──
    verification = _check_pending_verification(repo.full_name, run.head_branch)
    if verification:
        return await _handle_verification_failure(verification, run, repo, settings)

    # ── Repo allowlist ──
    if not settings.is_repo_allowed(repo.full_name):
        logger.warning(
            "webhook.repo_not_allowed",
            repo=repo.full_name,
            run_id=run.id,
        )
        return WebhookResponse(
            accepted=False,
            message=f"Repository not in allowlist: {repo.full_name}",
            run_id=run.id,
        )

    # ── Deduplication — skip if already processed ──
    if _is_duplicate(run.id):
        logger.info("webhook.duplicate_skipped", run_id=run.id)
        return WebhookResponse(
            accepted=False,
            message=f"Run {run.id} already processed (duplicate)",
            run_id=run.id,
        )

    # ── Create agent state and dispatch ──
    agent_state = AgentState(
        run_id=run.id,
        repo_full_name=repo.full_name,
        head_branch=run.head_branch,
        head_sha=run.head_sha,
        workflow_name=run.name,
        run_url=run.html_url,
    )

    logger.info(
        "webhook.accepted",
        run_id=run.id,
        repo=repo.full_name,
        branch=run.head_branch,
        sha=run.head_sha[:8],
        workflow=run.name,
    )

    # Dispatch to Celery task queue
    from src.tasks.repair_task import process_failure

    process_failure.delay(agent_state.model_dump())

    return WebhookResponse(
        accepted=True,
        message="Failure detected — repair task queued",
        run_id=run.id,
    )


async def _handle_pull_request_event(raw: dict) -> WebhookResponse | JSONResponse:
    """
    Handle pull_request webhook events — feedback loop.

    When a NeuroCI-created PR is merged or closed, update the vector store
    so the system learns from outcomes.
    """
    action = raw.get("action", "")
    pr = raw.get("pull_request", {})
    pr_number = pr.get("number", 0)
    pr_title = pr.get("title", "")
    merged = pr.get("merged", False)
    repo = raw.get("repository", {}).get("full_name", "")

    # Only process NeuroCI PRs
    if "NeuroCI" not in pr_title:
        return WebhookResponse(
            accepted=False,
            message="Not a NeuroCI PR — ignoring",
            run_id=pr_number,
        )

    # Only process closed events (merged or rejected)
    if action != "closed":
        return WebhookResponse(
            accepted=False,
            message=f"Ignoring PR action: {action}",
            run_id=pr_number,
        )

    outcome = "merged" if merged else "rejected"
    logger.info(
        "webhook.pr_feedback",
        pr_number=pr_number,
        outcome=outcome,
        repo=repo,
        title=pr_title,
    )

    # Extract run_id from PR title: "🧠 NeuroCI: Fix XYZ (run #12345)"
    run_id = _extract_run_id_from_title(pr_title)

    # ── Step 11: Register pending verification when a NeuroCI PR is merged ──
    if merged:
        pr.get("head", {}).get("ref", "")
        base_branch = pr.get("base", {}).get("ref", "main")
        _register_pending_verification(
            repo=repo,
            branch=base_branch,  # The pipeline re-runs on the merge target
            original_run_id=run_id,
            pr_number=pr_number,
        )

    # Dispatch feedback storage task
    from src.tasks.repair_task import store_feedback

    # Retrieve cached state from Redis to get failure details
    cached_data = _get_cached_state(run_id)
    if cached_data:
        store_feedback.delay(
            failure_log=cached_data.get("failure_log", ""),
            fix_diff=cached_data.get("fix_diff", ""),
            category=cached_data.get("category", "Unknown"),
            outcome=outcome,
            repo=repo,
            run_id=run_id,
        )
    else:
        # Minimal feedback even without cached state
        store_feedback.delay(
            failure_log=f"PR #{pr_number}: {pr_title}",
            fix_diff=pr.get("body", "")[:2000],
            category="Unknown",
            outcome=outcome,
            repo=repo,
            run_id=run_id,
        )

    return WebhookResponse(
        accepted=True,
        message=f"PR #{pr_number} {outcome} — feedback recorded",
        run_id=pr_number,
    )


def _extract_run_id_from_title(title: str) -> int:
    """Extract run ID from PR title like '🧠 NeuroCI: Fix XYZ (run #12345)'."""
    import re
    match = re.search(r"run\s*#?(\d+)", title)
    if match:
        return int(match.group(1))
    return 0


def _get_cached_state(run_id: int) -> dict | None:
    """Retrieve cached repair state from Redis."""
    if run_id == 0:
        return None
    r = _get_redis()
    if not r:
        return None
    try:
        cached = r.get(f"neuroci:state:{run_id}")
        r.close()
        if cached and isinstance(cached, (str, bytes)):
            state = json.loads(cached)
            return {
                "failure_log": state.get("parsed_error", {}).get("raw_log", "")[:4000],
                "fix_diff": state.get("patch", {}).get("unified_diff", "")[:4000],
                "category": state.get("category", "Unknown"),
            }
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════
# Step 11: Re-run Verification Helpers
# ═══════════════════════════════════════════════════════════

def _register_pending_verification(
    repo: str,
    branch: str,
    original_run_id: int,
    pr_number: int,
) -> None:
    """
    Register a pending verification in Redis.
    After a NeuroCI PR is merged, we watch for the next workflow_run
    on the target branch to confirm the fix worked.
    """
    r = _get_redis()
    if not r:
        return
    try:
        import time as _time
        key = f"neuroci:verification:{repo}:{branch}"
        data = json.dumps({
            "original_run_id": original_run_id,
            "pr_number": pr_number,
            "repo": repo,
            "branch": branch,
            "registered_at": _time.time(),
            "attempt": 1,
        })
        # Expire after 6 hours — if no pipeline runs by then, abandon verification
        r.setex(key, 21600, data)
        r.close()
        logger.info(
            "webhook.verification_registered",
            repo=repo, branch=branch,
            original_run_id=original_run_id, pr_number=pr_number,
        )
    except Exception as e:
        logger.warning("webhook.verification_register_failed", error=str(e))


def _check_pending_verification(repo: str, branch: str) -> dict | None:
    """
    Check if there's a pending verification for a repo/branch combination.
    Returns the verification data if found, None otherwise.
    """
    r = _get_redis()
    if not r:
        return None
    try:
        key = f"neuroci:verification:{repo}:{branch}"
        data = r.get(key)
        r.close()
        if data and isinstance(data, (str, bytes)):
            return json.loads(data)
    except Exception:
        pass
    return None


def _clear_pending_verification(repo: str, branch: str) -> None:
    """Remove a pending verification after it's been processed."""
    r = _get_redis()
    if not r:
        return
    try:
        r.delete(f"neuroci:verification:{repo}:{branch}")
        r.close()
    except Exception:
        pass


async def _handle_verification_success(
    verification: dict, run
) -> WebhookResponse:
    """
    Pipeline passed after a NeuroCI fix was merged — the fix worked!
    Send a Slack success notification with MTTR metrics.
    """
    import time as _time

    from src.metrics.prometheus import FIXES_TOTAL
    from src.notifications.slack_bot import send_verification_result

    original_run_id = verification.get("original_run_id", 0)
    pr_number = verification.get("pr_number", 0)
    registered_at = verification.get("registered_at", _time.time())
    repo = verification.get("repo", "")
    branch = verification.get("branch", "")

    # Calculate time from fix merge to pipeline pass
    verification_time = _time.time() - registered_at

    logger.info(
        "webhook.verification_success",
        original_run_id=original_run_id,
        pr_number=pr_number,
        verification_seconds=f"{verification_time:.1f}",
        run_id=run.id,
    )

    # Track success metric
    FIXES_TOTAL.labels(category="verified", result="success").inc()

    # Send Slack celebration 🎉
    await send_verification_result(
        repo=repo,
        branch=branch,
        original_run_id=original_run_id,
        pr_number=pr_number,
        success=True,
        verification_time=verification_time,
        run_url=run.html_url,
    )

    # Clear the pending verification
    _clear_pending_verification(repo, branch)

    return WebhookResponse(
        accepted=True,
        message=f"✅ Verification passed — NeuroCI fix for run #{original_run_id} confirmed working",
        run_id=run.id,
    )


async def _handle_verification_failure(
    verification: dict, run, repo, settings
) -> WebhookResponse:
    """
    Pipeline failed AGAIN after a NeuroCI fix was merged.
    If this is the first re-failure, trigger a second diagnostic cycle
    with context from the first attempt. Otherwise, escalate to human.
    """
    from src.metrics.prometheus import FIXES_TOTAL
    from src.notifications.slack_bot import send_verification_result

    original_run_id = verification.get("original_run_id", 0)
    pr_number = verification.get("pr_number", 0)
    attempt = verification.get("attempt", 1)
    branch = verification.get("branch", "")

    logger.warning(
        "webhook.verification_failure",
        original_run_id=original_run_id,
        pr_number=pr_number,
        attempt=attempt,
        run_id=run.id,
    )

    # Track failure metric
    FIXES_TOTAL.labels(category="verified", result="re_failure").inc()

    # Clear the pending verification
    _clear_pending_verification(repo.full_name, branch)

    if attempt >= 2:
        # Already retried once — escalate to human
        await send_verification_result(
            repo=repo.full_name,
            branch=branch,
            original_run_id=original_run_id,
            pr_number=pr_number,
            success=False,
            verification_time=0,
            run_url=run.html_url,
            escalated=True,
        )
        return WebhookResponse(
            accepted=True,
            message=f"❌ Fix for run #{original_run_id} failed again (attempt {attempt}) — escalating to human",
            run_id=run.id,
        )

    # First re-failure — trigger second diagnostic cycle with context
    await send_verification_result(
        repo=repo.full_name,
        branch=branch,
        original_run_id=original_run_id,
        pr_number=pr_number,
        success=False,
        verification_time=0,
        run_url=run.html_url,
    )

    # Dispatch a new repair task with context from the previous attempt
    agent_state = AgentState(
        run_id=run.id,
        repo_full_name=repo.full_name,
        head_branch=run.head_branch,
        head_sha=run.head_sha,
        workflow_name=run.name,
        run_url=run.html_url,
        retry_count=attempt,  # Carries context that this is a retry
    )

    from src.tasks.repair_task import process_failure
    process_failure.delay(agent_state.model_dump())

    return WebhookResponse(
        accepted=True,
        message=f"⚠️ Fix for run #{original_run_id} didn't hold — triggering second diagnostic cycle",
        run_id=run.id,
    )


@router.post(
    "/webhook/slack",
    summary="Receive Slack interactive message callbacks",
    status_code=status.HTTP_200_OK,
)
async def receive_slack_action(request: Request) -> dict[str, str]:
    """
    Handle Slack interactive message callbacks.
    When a developer clicks "Apply Fix" or "Dismiss" on a Slack notification.
    """
    form_data = await request.form()
    payload_val = form_data.get("payload", "")
    payload_str = payload_val if isinstance(payload_val, str) else ""

    try:
        payload = json.loads(payload_str)
    except Exception as e:
        logger.error("slack.parse_error", error=str(e))
        return {"text": "Error parsing Slack payload"}

    actions = payload.get("actions", [])
    if not actions:
        return {"text": "No action received"}

    action = actions[0]
    action_id = action.get("action_id", "")
    action_value = action.get("value", "")

    logger.info(
        "slack.action_received",
        action_id=action_id,
        value=action_value,
        user=payload.get("user", {}).get("name", "unknown"),
    )

    if action_id == "apply_fix":
        # Dispatch the PR creation task
        from src.tasks.repair_task import apply_approved_fix

        apply_approved_fix.delay(action_value)
        return {"text": "✅ Fix approved — creating PR now..."}

    elif action_id == "dismiss_fix":
        logger.info("slack.fix_dismissed", run_id=action_value)

        # Store dismissed fix as "rejected" feedback
        from src.tasks.repair_task import store_feedback

        cached = _get_cached_state(int(action_value) if action_value.isdigit() else 0)
        if cached:
            store_feedback.delay(
                failure_log=cached.get("failure_log", ""),
                fix_diff=cached.get("fix_diff", ""),
                category=cached.get("category", "Unknown"),
                outcome="dismissed",
                run_id=int(action_value) if action_value.isdigit() else 0,
            )

        return {"text": "❌ Fix dismissed. Logged for future reference."}

    return {"text": "Action processed"}
