"""FastAPI app serving the Baton API and the built web dashboard."""

import os
import secrets
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
PAGES = ("/", "/try", "/explore")


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
