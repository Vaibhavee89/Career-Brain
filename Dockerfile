FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    CAREERBRAIN_ROOT=/brain

# git is only used by the entrypoint to fetch the brain data at startup.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock Readme.md LICENSE ./
COPY src ./src
COPY scripts ./scripts
# --frozen: install exactly what uv.lock pins; --no-dev: skip ruff/pytest.
# --no-editable: copy the package into the venv instead of linking to /app/src.
RUN uv sync --frozen --no-dev --no-editable \
    && useradd --create-home --uid 1000 app

USER app
EXPOSE 8000

ENTRYPOINT ["sh", "scripts/entrypoint.sh"]
