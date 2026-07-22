# ── AMI Course Recommendation Engine ─────────────────────────────
# Multi-stage build:
#   builder  – installs Python dependencies via uv
#   runtime  – lean final image, non-root user

# ── Stage 1: builder ─────────────────────────────────────────────
FROM python:3.13-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install all dependencies into /app/.venv (no editable install needed)
RUN uv sync --frozen --no-dev

# ── Stage 2: runtime ─────────────────────────────────────────────
FROM python:3.13-slim

# psycopg2-binary needs libpq at runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user — never run web apps as root
RUN useradd --create-home --shell /bin/bash ami
WORKDIR /home/ami/app

# Copy the venv from builder stage (avoids re-installing in final image)
COPY --from=builder /app/.venv /home/ami/app/.venv

# Copy application code
COPY --chown=ami:ami . .

# Make entrypoint executable before switching user
RUN chmod +x entrypoint.sh

# Put venv on PATH
ENV PATH="/home/ami/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=ami_engine.settings

USER ami

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
