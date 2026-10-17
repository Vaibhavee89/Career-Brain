FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    CAREERBRAIN_ROOT=/brain

WORKDIR /app
COPY pyproject.toml Readme.md LICENSE ./
COPY src ./src
RUN uv pip install --system --no-cache . \
    && useradd --create-home --uid 1000 app

USER app
EXPOSE 8000

CMD ["python", "-m", "careerbrain.adapters.http_api", "--host", "0.0.0.0", "--port", "8000"]
