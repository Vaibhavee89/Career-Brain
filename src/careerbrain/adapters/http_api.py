from __future__ import annotations

import argparse
import math
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from careerbrain.adapters.cli import OfflineLLM
from careerbrain.adapters.client_ip import Network, parse_networks, resolve_client_ip
from careerbrain.bootstrap import Brain, open_brain
from careerbrain.core.answer_cache import AnswerCache, data_version
from careerbrain.core.engine import Engine
from careerbrain.core.llm import GroqProvider, LLMError, LLMProvider
from careerbrain.core.ratelimit import CooldownLimiter, WindowLimiter
from careerbrain.core.semantic import SemanticRetriever
from careerbrain.core.types import page_links, page_slug, page_title
from careerbrain.core.vector import sync_vectors
from careerbrain.site.build import render_markdown, without_title

API_KEY_ENV = "GROQ_API_KEY"
SITE_URL_ENV = "CAREERBRAIN_SITE_URL"
RESUME_URL_ENV = "CAREERBRAIN_RESUME_URL"
CORS_ORIGINS_ENV = "CAREERBRAIN_CORS_ORIGINS"
TRUSTED_PROXIES_ENV = "CAREERBRAIN_TRUSTED_PROXIES"
IP_RATE_MAX_ENV = "CAREERBRAIN_IP_RATE_MAX"
IP_RATE_WINDOW_ENV = "CAREERBRAIN_IP_RATE_WINDOW"
COOLDOWN_SECONDS = 1.0
DEFAULT_IP_RATE_MAX = 30
DEFAULT_IP_RATE_WINDOW = 60.0
HTTP_MESSAGE_LIMIT = 10_000
MAX_MESSAGE_CHARS = 2_000
MAX_USER_ID_CHARS = 128
EXEMPT_PATHS = frozenset({"/healthz"})


class AskRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=MAX_USER_ID_CHARS)
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class ResetRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=MAX_USER_ID_CHARS)


def build_app(
    engine: Engine,
    *,
    brain: Brain | None = None,
    cors_origins: Sequence[str] = (),
    trusted_proxies: Sequence[Network] = (),
    ip_limiter: WindowLimiter | None = None,
) -> FastAPI:
    app = FastAPI(title="Career Brain API")
    limiter = ip_limiter or WindowLimiter(DEFAULT_IP_RATE_MAX, DEFAULT_IP_RATE_WINDOW)

    if cors_origins:
        if "*" in cors_origins:
            raise ValueError("CORS origins must be listed explicitly, not '*'")
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cors_origins),
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )

    @app.middleware("http")
    async def limit_client_ip(
        request: Request, call_next: Callable[[Request], Response]
    ) -> Response:
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)
        client = resolve_client_ip(
            request.client.host if request.client else None,
            request.headers.get("x-forwarded-for"),
            trusted_proxies,
        )
        if not limiter.allow(client):
            return JSONResponse(
                status_code=429,
                content={"detail": "rate limit exceeded"},
                headers={"Retry-After": str(math.ceil(limiter.retry_after(client)))},
            )
        return await call_next(request)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/ask")
    def ask(body: AskRequest) -> JSONResponse:
        try:
            result = engine.handle(body.user_id, body.message, HTTP_MESSAGE_LIMIT)
        except LLMError:
            return JSONResponse(
                status_code=502,
                content={"detail": "language model unavailable"},
            )
        if result.kind == "rate_limited":
            return JSONResponse(
                status_code=429,
                content={"kind": result.kind, "retry_after": result.retry_after},
                headers={"Retry-After": str(math.ceil(result.retry_after))},
            )
        return JSONResponse(
            content={
                "kind": result.kind,
                "chunks": result.chunks,
                "sources": result.sources,
            }
        )

    @app.post("/reset")
    def reset(body: ResetRequest) -> dict[str, str]:
        engine.reset(body.user_id)
        return {"kind": "reset"}

    if brain is not None:

        @app.get("/pages")
        def list_pages() -> list[dict[str, str]]:
            return [
                {
                    "path": page.path,
                    "slug": page_slug(page.path),
                    "title": page_title(page),
                    "type": page.frontmatter.get("type", ""),
                }
                for page in brain.list_public_pages()
            ]

        @app.get("/pages/{slug}")
        def get_page(slug: str) -> JSONResponse:
            for page in brain.list_public_pages():
                if page_slug(page.path) != slug:
                    continue
                return JSONResponse(
                    content={
                        "path": page.path,
                        "slug": slug,
                        "title": page_title(page),
                        "type": page.frontmatter.get("type", ""),
                        "links": page_links(page.frontmatter),
                        "html": render_markdown(without_title(page.body)),
                    }
                )
            return JSONResponse(status_code=404, content={"detail": "page not found"})

    return app


def _env_list(name: str) -> list[str]:
    return [
        value.strip() for value in os.environ.get(name, "").split(",") if value.strip()
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the career brain over HTTP.")
    parser.add_argument("--root", type=Path, default=None, help="brain root directory")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="run without calling Groq; lists the pages a reply would use",
    )
    args = parser.parse_args(argv)

    llm: LLMProvider
    if args.offline:
        llm = OfflineLLM()
    else:
        api_key = os.environ.get(API_KEY_ENV)
        if not api_key:
            print(f"Set {API_KEY_ENV} or pass --offline.", file=sys.stderr)
            return 1
        llm = GroqProvider(api_key)

    try:
        brain = open_brain(args.root)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    vectors = sync_vectors(brain)
    engine = Engine(
        retriever=SemanticRetriever(brain, llm, vectors=vectors),
        llm=llm,
        limiter=CooldownLimiter(COOLDOWN_SECONDS),
        site_base_url=os.environ.get(SITE_URL_ENV),
        cache=AnswerCache(),
        data_version=data_version(brain.list_public_pages()),
        resume_url=os.environ.get(RESUME_URL_ENV),
    )
    app = build_app(
        engine,
        brain=brain,
        cors_origins=_env_list(CORS_ORIGINS_ENV),
        trusted_proxies=parse_networks(_env_list(TRUSTED_PROXIES_ENV)),
        ip_limiter=WindowLimiter(
            int(os.environ.get(IP_RATE_MAX_ENV, DEFAULT_IP_RATE_MAX)),
            float(os.environ.get(IP_RATE_WINDOW_ENV, DEFAULT_IP_RATE_WINDOW)),
        ),
    )
    # Uvicorn's own X-Forwarded-For handling would overwrite the peer address
    # before our trusted-proxy check runs, so it must stay off.
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
