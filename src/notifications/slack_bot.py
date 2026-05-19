"""
NeuroCI — Slack Bot Integration.

Sends rich interactive Slack messages:
- Fix notifications with diff previews and action buttons
- Escalation alerts for failures NeuroCI can't handle
- Summary notifications after PR creation
"""

from __future__ import annotations

from typing import Any

import structlog
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from src.config import get_settings
from src.models import AgentState

logger = structlog.get_logger()


def _get_slack_client() -> WebClient | None:
    """Get Slack client, returning None if not configured."""
    settings = get_settings()
    if not settings.slack_bot_token:
        return None
    return WebClient(token=settings.slack_bot_token)


def _confidence_bar(confidence: float) -> str:
    """Visual confidence meter for Slack."""
    filled = int(confidence * 10)
    return "█" * filled + "░" * (10 - filled)


async def send_fix_notification(state: AgentState, dry_run: bool = False) -> None:
    """
    Send a Slack notification for a generated fix.
    Includes: diff preview, confidence score, action buttons (if not dry_run).
    """
    client = _get_slack_client()
    if not client:
        logger.info("slack.not_configured")
        return

    settings = get_settings()
    patch = state.patch
    pe = state.parsed_error
    conf = patch.confidence if patch else 0
    diffs_preview = []
    if patch:
        for fp in patch.all_patches:
            diffs_preview.append(f"*{fp.target_file}*\n```diff\n{fp.unified_diff[:250]}\n```")
    diffs_preview_str = "\n".join(diffs_preview) or "N/A"

    title_text = "🧠 NeuroCI — Fix Available"
    if dry_run:
        title_text = "🧪 [DRY RUN] NeuroCI — Fix Generated"

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": title_text, "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Repository:*\n`{state.repo_full_name}`"},
                {"type": "mrkdwn", "text": f"*Category:*\n`{state.category.value}`"},
                {"type": "mrkdwn", "text": f"*Confidence:*\n{conf:.0%} [{_confidence_bar(conf)}]"},
                {"type": "mrkdwn", "text": f"*Branch:*\n`{state.head_branch}`"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Error:* `{pe.error_type}: {pe.error_message[:100]}`" if pe else "*Error:* Unknown",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Proposed Fix:*\n{diffs_preview_str[:1500]}",
            },
        },
    ]

    # Only add actions if not dry_run
    if not dry_run:
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ Apply Fix"},
                    "style": "primary",
                    "action_id": "apply_fix",
                    "value": str(state.run_id),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "❌ Dismiss"},
                    "style": "danger",
                    "action_id": "dismiss_fix",
                    "value": str(state.run_id),
                },
            ],
        })

    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": f"<{state.run_url}|View Failed Run> · Run #{state.run_id}"},
        ],
    })

    try:
        client.chat_postMessage(
            channel=settings.slack_channel,
            blocks=blocks,
            text=f"NeuroCI fix available for {state.repo_full_name} ({state.category.value})",
        )
        logger.info("slack.fix_sent", run_id=state.run_id, channel=settings.slack_channel)
    except SlackApiError as e:
        logger.error("slack.send_error", error=str(e))


async def send_escalation(state: AgentState, reason: str) -> None:
    """Send a Slack alert when NeuroCI cannot auto-fix."""
    client = _get_slack_client()
    if not client:
        return

    settings = get_settings()

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "⚠️ NeuroCI — Manual Attention Needed"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Repo:*\n`{state.repo_full_name}`"},
                {"type": "mrkdwn", "text": f"*Category:*\n`{state.category.value}`"},
                {"type": "mrkdwn", "text": f"*Reason:*\n{reason}"},
                {"type": "mrkdwn", "text": f"*Branch:*\n`{state.head_branch}`"},
            ],
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"<{state.run_url}|View Failed Run>"},
            ],
        },
    ]

    try:
        client.chat_postMessage(
            channel=settings.slack_channel,
            blocks=blocks,
            text=f"NeuroCI escalation: {reason}",
        )
        logger.info("slack.escalation_sent", run_id=state.run_id)
    except SlackApiError as e:
        logger.error("slack.escalation_error", error=str(e))


async def send_pr_created(state: AgentState, pr_url: str) -> None:
    """Notify Slack when a PR has been auto-created."""
    client = _get_slack_client()
    if not client:
        return

    settings = get_settings()
    patch = state.patch
    confidence = patch.confidence if patch else 0.0

    try:
        client.chat_postMessage(
            channel=settings.slack_channel,
            text=(
                f"✅ *NeuroCI auto-created PR* for `{state.repo_full_name}`\n"
                f"Category: `{state.category.value}` | "
                f"Confidence: {confidence:.0%}\n"
                f"<{pr_url}|View Pull Request>"
            ),
        )
    except SlackApiError as e:
        logger.error("slack.pr_notify_error", error=str(e))


async def send_verification_result(
    repo: str,
    branch: str,
    original_run_id: int,
    pr_number: int,
    success: bool,
    verification_time: float,
    run_url: str = "",
    escalated: bool = False,
) -> None:
    """
    Send Slack notification for post-merge pipeline verification (Step 11).

    - Success: celebration message with MTTR metrics
    - Failure: warning with retry or escalation notice
    """
    client = _get_slack_client()
    if not client:
        return

    settings = get_settings()

    if success:
        # Format verification time
        if verification_time < 60:
            time_str = f"{verification_time:.0f}s"
        elif verification_time < 3600:
            time_str = f"{verification_time / 60:.1f}min"
        else:
            time_str = f"{verification_time / 3600:.1f}h"

        text = (
            f"🎉 *NeuroCI Fix Verified!*\n"
            f"Pipeline passed after NeuroCI fix was merged.\n\n"
            f"*Repository:* `{repo}`\n"
            f"*Branch:* `{branch}`\n"
            f"*Original failure:* run #{original_run_id}\n"
            f"*Fix PR:* #{pr_number}\n"
            f"*Verification time:* {time_str}\n"
            f"<{run_url}|View Passing Run>"
        )
    elif escalated:
        text = (
            f"🚨 *NeuroCI Fix Failed — Human Needed*\n"
            f"The fix for run #{original_run_id} failed again after a second attempt.\n"
            f"Manual intervention required.\n\n"
            f"*Repository:* `{repo}`\n"
            f"*Branch:* `{branch}`\n"
            f"*Fix PR:* #{pr_number}\n"
            f"<{run_url}|View Failed Run>"
        )
    else:
        text = (
            f"⚠️ *NeuroCI Fix Didn't Hold*\n"
            f"Pipeline failed again after merging the fix for run #{original_run_id}.\n"
            f"Triggering a second diagnostic cycle with additional context.\n\n"
            f"*Repository:* `{repo}`\n"
            f"*Branch:* `{branch}`\n"
            f"*Fix PR:* #{pr_number}\n"
            f"<{run_url}|View Failed Run>"
        )

    try:
        client.chat_postMessage(
            channel=settings.slack_channel,
            text=text,
        )
        logger.info(
            "slack.verification_sent",
            success=success,
            original_run_id=original_run_id,
            escalated=escalated,
        )
    except SlackApiError as e:
        logger.error("slack.verification_error", error=str(e))
