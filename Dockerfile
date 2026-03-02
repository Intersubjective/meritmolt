# Build stage: install dependencies with uv
FROM python:3.14-slim AS builder

WORKDIR /app

# Cache uv's download in a dir we don't copy to final image
ENV UV_CACHE_DIR=/tmp/uvcache
ENV UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
COPY meritmolt/ meritmolt/
COPY textlake/ textlake/

RUN uv sync --frozen --no-dev \
    && find /app -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true \
    && find /app -type f -name "*.pyc" -delete 2>/dev/null || true

# Runtime stage: minimal image, no uv
FROM python:3.14-slim AS runtime

WORKDIR /app

# Avoid storing pip/uv cache in the image
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Copy venv and app from builder (editable install needs source)
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/meritmolt /app/meritmolt
COPY --from=builder /app/textlake /app/textlake
COPY --from=builder /app/pyproject.toml /app/pyproject.toml

ENV PATH="/app/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/app/.venv"

# Default for meritmolt service; textlake overrides in compose
CMD ["python", "-m", "uvicorn", "meritmolt.main:app", "--host", "0.0.0.0", "--port", "8000"]
