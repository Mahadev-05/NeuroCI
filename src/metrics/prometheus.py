"""
NeuroCI — Prometheus Metrics.

Exposes metrics for Grafana dashboards:
- Fix counts by category and result
- Confidence score histogram
- MTTR tracking
- Fix accuracy (rolling 7-day)
"""

from __future__ import annotations

import time

import structlog
from prometheus_client import Counter, Gauge, Histogram, Info

from src.models import AgentState

logger = structlog.get_logger()

# ═══════════════════════════════════════════════════════════
# Metric Definitions
# ═══════════════════════════════════════════════════════════

# Total fix attempts by category and result
FIXES_TOTAL = Counter(
    "neuroci_fixes_total",
    "Total fix attempts",
    ["category", "result"],  # result: auto_pr, slack_approval, escalated, skipped, error
)

# Confidence score distribution
CONFIDENCE_HISTOGRAM = Histogram(
    "neuroci_confidence_score",
    "Distribution of patch confidence scores",
    ["category"],
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0],
)

# Mean Time To Repair (seconds from webhook to PR)
MTTR_HISTOGRAM = Histogram(
    "neuroci_mttr_seconds",
    "Time from failure detection to PR creation",
    buckets=[10, 30, 60, 120, 300, 600, 1800],
)

# Rolling 7-day fix accuracy
FIX_ACCURACY_7D = Gauge(
    "neuroci_fix_accuracy_7d",
    "Rolling 7-day fix accuracy (merged / total PRs)",
)

# Active repairs in progress
ACTIVE_REPAIRS = Gauge(
    "neuroci_active_repairs",
    "Number of repair tasks currently processing",
)

# Webhook events received
WEBHOOKS_RECEIVED = Counter(
    "neuroci_webhooks_received_total",
    "Total webhook events received",
    ["action", "conclusion"],
)

# System info
SYSTEM_INFO = Info(
    "neuroci",
    "NeuroCI system information",
)

# Pipeline stage durations
STAGE_DURATION = Histogram(
    "neuroci_stage_duration_seconds",
    "Duration of each pipeline stage",
    ["stage"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60],
)


def setup_metrics() -> None:
    """Initialize metrics with system info."""
    SYSTEM_INFO.info({
        "version": "1.0.0",
        "service": "neuroci",
    })
    logger.info("metrics.initialized")


def track_repair_attempt(state: AgentState) -> None:
    """Record metrics for a completed repair attempt."""
    result = state.result
    if not result:
        return

    # Fix count
    FIXES_TOTAL.labels(
        category=state.category.value,
        result=result.action_taken,
    ).inc()

    # Confidence score
    if state.patch and state.patch.confidence > 0:
        CONFIDENCE_HISTOGRAM.labels(
            category=state.category.value,
        ).observe(state.patch.confidence)

    logger.info(
        "metrics.tracked",
        run_id=state.run_id,
        category=state.category.value,
        action=result.action_taken,
        confidence=state.patch.confidence if state.patch else 0,
    )


def track_webhook(action: str, conclusion: str) -> None:
    """Track incoming webhook events."""
    WEBHOOKS_RECEIVED.labels(action=action, conclusion=conclusion).inc()


class StageTimer:
    """Context manager for timing pipeline stages."""

    def __init__(self, stage_name: str):
        self.stage = stage_name
        self.start: float = 0

    def __enter__(self):
        self.start = time.monotonic()
        return self

    def __exit__(self, *args):
        duration = time.monotonic() - self.start
        STAGE_DURATION.labels(stage=self.stage).observe(duration)
        logger.debug("metrics.stage_duration", stage=self.stage, duration_s=f"{duration:.2f}")
