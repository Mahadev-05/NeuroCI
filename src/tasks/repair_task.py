"""
NeuroCI — Celery Task Definitions.

Async tasks that run in Celery workers:
- process_failure: Main repair pipeline (webhook → PR)
- apply_approved_fix: Create PR after Slack approval
- store_feedback: Update vector store with fix outcomes
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from celery import Celery

from src.config import get_settings

logger = structlog.get_logger()

# ── Celery App ─────────────────────────────────────────────
settings = get_settings()
celery_app = Celery(
    "neuroci",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=120,
    task_time_limit=180,
)


def _run_async(coro):
    """Helper to run async functions in Celery's sync context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    name="neuroci.process_failure",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def process_failure(self, state_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Main repair task — runs the full NeuroCI pipeline.

    Receives the AgentState as a dict (serialized by the webhook receiver).
    Returns the final state dict with repair results.
    """
    from src.models import AgentState
    from src.agent.repair_agent import run_repair_pipeline
    from src.metrics.prometheus import ACTIVE_REPAIRS

    ACTIVE_REPAIRS.inc()

    try:
        state = AgentState(**state_dict)
        logger.info(
            "task.process_failure.start",
            run_id=state.run_id,
            repo=state.repo_full_name,
            task_id=self.request.id,
        )

        # Run the async repair pipeline
        result_state = _run_async(run_repair_pipeline(state))

        logger.info(
            "task.process_failure.complete",
            run_id=state.run_id,
            success=result_state.result.success if result_state.result else False,
            action=result_state.result.action_taken if result_state.result else "unknown",
        )

        return result_state.model_dump()

    except Exception as exc:
        logger.error(
            "task.process_failure.error",
            error=str(exc),
            run_id=state_dict.get("run_id"),
        )
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 30)

    finally:
        ACTIVE_REPAIRS.dec()


@celery_app.task(name="neuroci.apply_approved_fix")
def apply_approved_fix(run_id_str: str) -> dict[str, str]:
    """
    Create a PR after a developer clicks "Apply Fix" in Slack.
    Retrieves the cached state from Redis and creates the PR.
    """
    import redis as redis_lib

    logger.info("task.apply_fix.start", run_id=run_id_str)

    try:
        r = redis_lib.from_url(settings.redis_url)
        cached = r.get(f"neuroci:state:{run_id_str}")

        if not cached:
            logger.warning("task.apply_fix.no_cached_state", run_id=run_id_str)
            return {"status": "error", "message": "No cached state found"}

        import json
        from src.models import AgentState
        from src.agent.repair_agent import _create_fix_pr
        from src.pipeline.github_client import GitHubClient

        state = AgentState(**json.loads(cached))
        github = GitHubClient()

        pr_data = _run_async(_create_fix_pr(github, state))
        pr_url = pr_data.get("html_url", "")
        _run_async(github.close())

        logger.info("task.apply_fix.complete", run_id=run_id_str, pr_url=pr_url)
        return {"status": "success", "pr_url": pr_url}

    except Exception as e:
        logger.error("task.apply_fix.error", error=str(e))
        return {"status": "error", "message": str(e)}


@celery_app.task(name="neuroci.store_feedback")
def store_feedback(
    failure_log: str,
    fix_diff: str,
    category: str,
    outcome: str,
    repo: str = "",
    run_id: int = 0,
) -> dict[str, str]:
    """
    Store fix outcome in the vector store (feedback loop).
    Called when a PR is merged or rejected.
    """
    from src.memory.vector_store import VectorStore

    try:
        vs = VectorStore()
        _run_async(vs.store_fix(
            failure_log=failure_log,
            fix_diff=fix_diff,
            category=category,
            outcome=outcome,
            repo=repo,
            run_id=run_id,
        ))
        logger.info("task.feedback.stored", outcome=outcome, run_id=run_id)
        return {"status": "stored"}
    except Exception as e:
        logger.error("task.feedback.error", error=str(e))
        return {"status": "error", "message": str(e)}
