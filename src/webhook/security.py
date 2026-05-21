"""
NeuroCI — Webhook Security.

HMAC-SHA256 signature verification for GitHub webhook payloads.
Ensures only legitimate GitHub-signed events are processed.
"""

from __future__ import annotations

import hashlib
import hmac

import structlog
from fastapi import HTTPException, Request, status

from src.config import get_settings

logger = structlog.get_logger()


async def verify_github_signature(request: Request) -> bytes:
    """
    Verify the HMAC-SHA256 signature on a GitHub webhook request.

    GitHub signs every webhook payload with the shared secret using
    HMAC-SHA256. The signature is sent in the X-Hub-Signature-256 header.

    Returns the raw request body if verification succeeds.
    Raises HTTP 403 if verification fails.
    """
    settings = get_settings()

    # ── Get signature header ──
    signature_header: str | None = request.headers.get("X-Hub-Signature-256")
    if not signature_header:
        logger.warning(
            "webhook.security.missing_signature",
            remote_addr=request.client.host if request.client else "unknown",
            github_event=request.headers.get("X-GitHub-Event", "unknown"),
            delivery_id=request.headers.get("X-GitHub-Delivery", "unknown"),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing X-Hub-Signature-256 header",
        )

    # ── Read body ──
    body = await request.body()

    # ── Compute expected signature ──
    expected_signature = (
        "sha256="
        + hmac.new(
            key=settings.github_webhook_secret.encode("utf-8"),
            msg=body,
            digestmod=hashlib.sha256,
        ).hexdigest()
    )

    # ── Validate header format first ──
    if not signature_header.startswith("sha256="):
        logger.warning(
            "webhook.security.invalid_signature_format",
            remote_addr=request.client.host if request.client else "unknown",
            received=signature_header,
            github_event=request.headers.get("X-GitHub-Event", "unknown"),
            delivery_id=request.headers.get("X-GitHub-Delivery", "unknown"),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid X-Hub-Signature-256 header format",
        )

    # ── Constant-time comparison ──
    if not hmac.compare_digest(expected_signature, signature_header):
        logger.warning(
            "webhook.security.invalid_signature",
            remote_addr=request.client.host if request.client else "unknown",
            received=signature_header[:20] + "...",
            expected_length=len(expected_signature),
            github_event=request.headers.get("X-GitHub-Event", "unknown"),
            delivery_id=request.headers.get("X-GitHub-Delivery", "unknown"),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature",
        )

    logger.info(
        "webhook.security.verified",
        payload_size=len(body),
        github_event=request.headers.get("X-GitHub-Event", "unknown"),
        delivery_id=request.headers.get("X-GitHub-Delivery", "unknown"),
        verification_status="passed",
    )
    return body


def compute_signature(payload: bytes, secret: str) -> str:
    """
    Compute an HMAC-SHA256 signature for a payload.
    Useful for testing and for re-signing forwarded webhooks.
    """
    return (
        "sha256="
        + hmac.new(
            key=secret.encode("utf-8"),
            msg=payload,
            digestmod=hashlib.sha256,
        ).hexdigest()
    )
