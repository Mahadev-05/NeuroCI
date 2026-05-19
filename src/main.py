"""
NeuroCI — FastAPI Application Entry Point.

The main application server that:
- Receives GitHub webhook events
- Exposes health, readiness, and metrics endpoints
- Configures structured logging
- Registers all routers
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import redis as redis_lib
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from src.config import get_settings
from src.metrics.prometheus import (
    FIXES_TOTAL,
    setup_metrics,
)
from src.models import HealthResponse, MetricsSnapshot
from src.webhook.receiver import router as webhook_router


# ── Structured Logging ─────────────────────────────────────
def configure_logging() -> None:
    """Configure structlog for JSON-formatted structured logging."""
    import logging
    settings = get_settings()

    # Map log level string to numeric level
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


# ── Lifespan ───────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup/shutdown lifecycle."""
    log = structlog.get_logger()

    # Startup
    configure_logging()
    setup_metrics()
    log.info("neuroci.startup", version="1.0.0", message="NeuroCI is online 🧠")

    yield

    # Shutdown
    log.info("neuroci.shutdown", message="NeuroCI shutting down")


# ── FastAPI App ────────────────────────────────────────────
app = FastAPI(
    title="NeuroCI",
    description="AI-native autonomous CI/CD repair system — the self-healing pipeline",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — restrict to known origins in production
settings = get_settings()
_cors_origins = ["https://github.com", "https://hooks.slack.com"]
if settings.log_level == "DEBUG":
    _cors_origins.append("*")  # Allow all in debug mode

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

# ── Mount Prometheus metrics endpoint ──────────────────────
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# ── Register Routers ──────────────────────────────────────
app.include_router(webhook_router, prefix="/api/v1", tags=["Webhooks"])


# ── Health Check ───────────────────────────────────────────
@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check() -> HealthResponse:
    """Health check endpoint for Kubernetes liveness probes."""
    return HealthResponse()


@app.get("/ready", response_model=HealthResponse, tags=["Health"])
async def readiness_check() -> HealthResponse | JSONResponse:
    """
    Readiness check — verifies downstream dependencies.
    Kubernetes uses this to determine if the pod should receive traffic.
    """
    settings = get_settings()
    checks: dict[str, bool] = {}

    # ── Redis connectivity ──
    try:
        r = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
        r.ping()
        r.close()
        checks["redis"] = True
    except Exception:
        checks["redis"] = False

    # ── ChromaDB connectivity ──
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"http://{settings.chroma_host}:{settings.chroma_port}/api/v1/heartbeat")
            checks["chromadb"] = resp.status_code == 200
    except Exception:
        checks["chromadb"] = False

    # ── OPA connectivity ──
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.opa_url}/health")
            checks["opa"] = resp.status_code == 200
    except Exception:
        checks["opa"] = False

    # All critical services must be ready
    all_ready = checks.get("redis", False)  # Redis is required
    # ChromaDB and OPA are degraded-mode tolerant
    status_str = "ready" if all_ready else "not_ready"

    log = structlog.get_logger()
    log.debug("readiness.check", checks=checks, status=status_str)

    if not all_ready:
        return JSONResponse(
            status_code=503,
            content={
                "status": status_str,
                "version": "1.0.0",
                "checks": checks,
            },
        )

    return HealthResponse(status=status_str)


# ── Metrics Snapshot API ──────────────────────────────────
@app.get("/api/v1/metrics/snapshot", response_model=MetricsSnapshot, tags=["Metrics"])
async def metrics_snapshot() -> MetricsSnapshot:
    """
    Return a structured metrics snapshot for API consumers.
    Useful for dashboards, alerting, or external integrations.
    """
    # Aggregate fix counts by category from Prometheus counters
    fixes_by_category: dict[str, int] = {}
    total_fixes = 0
    total_prs = 0

    try:
        # Iterate over Prometheus metric samples
        metrics_list = list(FIXES_TOTAL.collect())
        if metrics_list:
            for sample in metrics_list[0].samples:
                cat = sample.labels.get("category", "Unknown")
                result = sample.labels.get("result", "")
                count = int(sample.value)
                total_fixes += count
                fixes_by_category[cat] = fixes_by_category.get(cat, 0) + count
                if result in ("auto_pr", "slack_approval"):
                    total_prs += count
    except Exception:
        pass

    return MetricsSnapshot(
        total_failures_processed=total_fixes,
        total_fixes_attempted=total_prs,
        fixes_by_category=fixes_by_category,
    )


# ── Root ───────────────────────────────────────────────────
@app.get("/", tags=["Root"])
async def root() -> dict[str, str]:
    return {
        "service": "NeuroCI",
        "version": "1.0.0",
        "description": "The Self-Healing Pipeline",
        "docs": "/docs",
    }

# ── Status ─────────────────────────────────────────────────
@app.get("/status", tags=["Health"])
async def status_endpoint() -> dict[str, Any]:
    """Status endpoint returning detailed health and metric info."""
    settings = get_settings()

    redis_connected = False
    queue_depth = 0
    chromadb_connected = False
    total_fixes_today = 0

    # Check Redis & Queue depth
    try:
        r = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
        if r.ping():
            redis_connected = True
            # Get celery queue depth
            queue_depth = r.llen("celery")
        r.close()
    except Exception:
        pass

    # Check ChromaDB
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"http://{settings.chroma_host}:{settings.chroma_port}/api/v1/heartbeat")
            if resp.status_code == 200:
                chromadb_connected = True
    except Exception:
        pass

    # Get total fixes today from metrics
    try:
        metrics_list = list(FIXES_TOTAL.collect())
        if metrics_list:
            for sample in metrics_list[0].samples:
                total_fixes_today += int(sample.value)
    except Exception:
        pass

    return {
        "redis_connected": redis_connected,
        "chromadb_connected": chromadb_connected,
        "llm_provider": settings.llm_provider,
        "total_fixes_today": total_fixes_today,
        "queue_depth": queue_depth
    }
