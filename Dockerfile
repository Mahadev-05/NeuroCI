# ═══════════════════════════════════════════════════════════
# NeuroCI — Production Dockerfile
# Multi-stage build for minimal image size
# ═══════════════════════════════════════════════════════════

FROM python:3.11-slim AS base

# Prevent Python from writing bytecode and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ── Stage 1: Dependencies ──────────────────────────────────
FROM base AS deps

COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install ".[dev]"

# ── Stage 2: Application ──────────────────────────────────
FROM base AS runtime

# Install only production dependencies
COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install .

# Copy application code
COPY src/ ./src/
COPY policies/ ./policies/

# Create non-root user
RUN addgroup --system neuroci && \
    adduser --system --ingroup neuroci neuroci
USER neuroci

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()"

# Expose port
EXPOSE 8000

# Default command: run the FastAPI server
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
