"""FastAPI app serving the Baton API and the built web dashboard."""

import os
import secrets
import time
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import fake_service
from baton import service as real_service
from baton.models import Issue

WEB_DIST = Path(os.environ.get("BATON_WEB_DIST", Path(__file__).resolve().parent.parent / "web" / "dist"))
PAGES = ("/", "/try", "/explore", "/connect")
PER_CLIENT_LIMITS = {"/route": 30, "/learn": 10, "/graph": 60, "/curve": 60, "/stats": 60}
DEFAULT_PER_CLIENT_LIMIT = 300
GLOBAL_LIMIT = 1200
MAX_BODY_BYTES = 64_000


class RateLimiter:
    """Per-minute request caps per client and path, plus one cap across all clients."""

    def __init__(self, per_client: dict[str, int], default: int, total: int) -> None:
        self.per_client, self.default, self.total = per_client, default, total
        self.window = -1
        self.counts: Counter[tuple[str, str]] = Counter()
        self.served = 0

    def retry_after(self, client: str, path: str) -> int:
        """Admit and count a request (returns 0), or return the seconds until the current minute ends."""
        now = time.time()
        if int(now // 60) != self.window:
            self.window, self.counts, self.served = int(now // 60), Counter(), 0
        bucket = path if path in self.per_client else "*"
        if self.counts[client, bucket] >= self.per_client.get(bucket, self.default) or self.served >= self.total:
            return 60 - int(now % 60)
        self.counts[client, bucket] += 1
        self.served += 1
        return 0


def client_ip(request: Request) -> str:
    """The address Cloud Run's front end appended last to X-Forwarded-For, else the socket peer."""
    forwarded = request.headers.get("x-forwarded-for", "").rsplit(",", 1)[-1].strip()
    return forwarded or (request.client.host if request.client else "unknown")


class RouteRequest(BaseModel):
    """Body of POST /route."""

    title: str = Field(min_length=1, max_length=500)
    body: str = Field(default="", max_length=50_000)
    reporter: str = Field(default="", max_length=100)
    as_of: Literal[0, 500, 1000, 1700] | None = None


class LearnRequest(BaseModel):
    """Body of POST /learn: an Issue plus the team that really fixed it."""

    number: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(default="", max_length=50_000)
    created_at: str = Field(min_length=1)
    reporter: str = Field(default="", max_length=100)
    sigs: list[str] = Field(default_factory=list)
    team: str = Field(min_length=1, max_length=100)

    def to_issue(self) -> Issue:
        """Convert to the shared Issue model."""
        return Issue(
            number=self.number,
            title=self.title,
            body=self.body,
            created_at=self.created_at,
            reporter=self.reporter,
            sigs=tuple(self.sigs),
        )


def create_app(service: ModuleType, learn_token: str | None = None) -> FastAPI:
    """Build the app against a service module; when `learn_token` is set, POST /learn needs it as a bearer token."""
    app = FastAPI(title="Baton", version="0.1.0")
    limiter = RateLimiter(PER_CLIENT_LIMITS, DEFAULT_PER_CLIENT_LIMIT, GLOBAL_LIMIT)

    @app.middleware("http")
    async def guard(request: Request, call_next) -> Response:
        if int(request.headers.get("content-length") or 0) > MAX_BODY_BYTES:
            return JSONResponse(status_code=413, content={"error": "too_large", "detail": f"Request bodies are capped at {MAX_BODY_BYTES} bytes"})
        wait = limiter.retry_after(client_ip(request), request.url.path)
        if wait:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(wait)},
                content={"error": "rate_limited", "detail": f"Too many requests. Retry in {wait} seconds."},
            )
        return await call_next(request)

    @app.exception_handler(NotImplementedError)
    async def service_not_ready(request: Request, exc: NotImplementedError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": "service_unavailable",
                "detail": f"The Baton service does not implement {request.url.path} yet. Set BATON_FAKE_SERVICE=1 to use demo data.",
            },
        )

    @app.post("/route")
    def route(req: RouteRequest) -> dict:
        return service.route_issue(req.title, req.body, req.reporter, req.as_of).to_dict()

    @app.post("/learn")
    def learn(req: LearnRequest, authorization: str = Header(default="")) -> dict:
        if learn_token and not secrets.compare_digest(authorization.encode(), f"Bearer {learn_token}".encode()):
            raise HTTPException(status_code=401, detail="POST /learn needs the BATON_LEARN_TOKEN bearer token")
        return service.record_outcome(req.to_issue(), req.team)

    @app.get("/curve")
    def curve() -> dict:
        return service.curve()

    @app.get("/graph")
    def graph(entity: str = Query(min_length=1, max_length=200)) -> dict:
        return service.graph_around(entity.strip())

    @app.get("/stats")
    def stats() -> dict:
        return service.stats()

    def page() -> Response:
        index = WEB_DIST / "index.html"
        if not index.exists():
            return PlainTextResponse("The dashboard is not built. Run: cd web && npm ci && npm run build", status_code=503)
        return FileResponse(index)

    for path in PAGES:
        app.add_api_route(path, page, methods=["GET"], include_in_schema=False)
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets", check_dir=False), name="assets")
    return app


app = create_app(fake_service if os.environ.get("BATON_FAKE_SERVICE") == "1" else real_service, os.environ.get("BATON_LEARN_TOKEN") or None)
