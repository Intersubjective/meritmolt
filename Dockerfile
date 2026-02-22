FROM python:3.14-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
COPY meritmolt/ meritmolt/
RUN uv sync --frozen --no-dev

CMD ["uv", "run", "uvicorn", "meritmolt.main:app", "--host", "0.0.0.0", "--port", "8000"]
