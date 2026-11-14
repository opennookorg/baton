"""FastAPI app serving the Baton API and the dashboard page."""

import os
from pathlib import Path
from types import ModuleType
from typing import Literal

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import fake_service
from baton import service as real_service
from baton.models import Issue

STATIC_DIR = Path(__file__).resolve().parent / "static"


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


def create_app(service: ModuleType) -> FastAPI:
    """Build the app against a service module exposing the baton.service functions."""
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
    def learn(req: LearnRequest) -> dict:
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

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app(fake_service if os.environ.get("BATON_FAKE_SERVICE") == "1" else real_service)
