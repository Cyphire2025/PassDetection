# ============================================================
# Backend Dockerfile — Multi-stage build
# ============================================================
# Stage 1: builder  — installs dependencies
# Stage 2: runtime  — minimal image with no build tools
# ============================================================

# ── Stage 1: Dependency Builder ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

ARG PIP_VERSION=26.1.2

WORKDIR /build

# System dependencies required for C extensions (OpenCV, psycopg2, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies into a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.lock .
RUN python -m pip install --no-cache-dir "pip==${PIP_VERSION}" && \
    pip install --no-cache-dir --require-hashes -r requirements.lock

# ── Stage 2: Production Runtime ──────────────────────────────────────────────
FROM python:3.11-slim AS runtime

ARG APP_REVISION=unknown

LABEL maintainer="Global Connects Dashboard Team"
LABEL version="1.0.0"
LABEL description="Global Connects Dashboard - Backend API"
LABEL org.opencontainers.image.revision="${APP_REVISION}"

ENV APP_REVISION="${APP_REVISION}"

# Runtime system libraries only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for security
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application source
COPY --chown=appuser:appgroup . .

# Switch to non-root user
USER appuser

EXPOSE 8000

# Health check used by Docker Compose and Kubernetes
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/api/v1/health/live').raise_for_status()"

# The config validates WEB_CONCURRENCY and the aggregate PostgreSQL connection
# budget before Gunicorn forks any API worker.
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app.main:app"]
