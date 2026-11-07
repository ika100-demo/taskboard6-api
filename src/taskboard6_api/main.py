"""FastAPI entry point for taskboard6-api."""

from __future__ import annotations

import os

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from . import __version__, tasks
from .db import Database, StorageUnavailableError
from .logging_config import configure_logging
from .metrics import MetricsMiddleware
from .tasks.pg_store import PostgresTaskStore
from .tracing import configure_tracing, tracing_enabled

configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
if tracing_enabled():
    configure_tracing()

logger = structlog.get_logger(__name__)


class HealthResponse(BaseModel):
    status: str


def create_app(database_url: str | None = None) -> FastAPI:
    """Build the application; no database access happens here."""
    application = FastAPI(title="taskboard6-api", version=__version__)
    application.add_middleware(MetricsMiddleware)
    application.include_router(tasks.router)
    application.state.database = Database(database_url)
    application.state.task_store = PostgresTaskStore(application.state.database)

    @application.exception_handler(StorageUnavailableError)
    def storage_unavailable(request: Request, exc: Exception) -> JSONResponse:
        cause = exc.__cause__
        logger.warning(
            "task_storage_unavailable",
            error_type=type(cause if cause is not None else exc).__name__,
            error=str(exc),
        )
        return JSONResponse(status_code=503, content={"detail": "Task storage is unavailable"})

    @application.exception_handler(Exception)
    def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Liveness probe — returns 200 as long as the process is responding."""
        return HealthResponse(status="ok")

    @application.get("/ready", response_model=HealthResponse, responses={503: {}})
    def ready(request: Request) -> Response:
        """Readiness probe — 200 when the database answers."""
        if request.app.state.database.ping():
            return JSONResponse(status_code=200, content={"status": "ready"})
        return JSONResponse(status_code=503, content={"status": "not ready"})

    @application.get("/ping")
    def ping() -> dict[str, str]:
        """Simple ping endpoint."""
        return {"pong": "taskboard6-api"}

    @application.get("/metrics")
    def metrics() -> Response:
        """Prometheus scrape endpoint."""
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return application


app = create_app()
