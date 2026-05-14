"""FastAPI entrypoint for ReportForge."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.database import init_db
from app.logging_config import configure_logging, get_logger
from app.routers import costs, export, jobs, sections
from tools.llm.model_router import ModelRouter
from tools.llm.quota_manager import QuotaExceededError
from tools.storage import StorageManager

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize storage, logging, and database tables."""
    configure_logging()
    StorageManager().ensure()
    init_db()
    app.state.model_router = ModelRouter()
    app.state.active_model = app.state.model_router.get_model()
    app.state.shutting_down = False
    logger.info("app_started", provider=app.state.active_model.provider, model=app.state.active_model.model_name)
    yield
    app.state.shutting_down = True
    logger.info("app_shutdown")


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    app = FastAPI(title="ReportForge", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(jobs.router)
    app.include_router(sections.router)
    app.include_router(export.router)
    app.include_router(costs.router)

    @app.exception_handler(404)
    async def not_found_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        """Return normalized 404 errors."""
        return JSONResponse(status_code=404, content={"detail": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        """Return normalized validation errors."""
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    @app.exception_handler(QuotaExceededError)
    async def quota_handler(_request: Request, exc: QuotaExceededError) -> JSONResponse:
        """Return 429 for provider quota exhaustion."""
        return JSONResponse(status_code=429, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        """Trace unexpected failures without leaking internals."""
        logger.exception("unhandled_request_error", path=str(request.url.path), error=str(exc))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "internal server error"},
        )

    @app.get("/health")
    async def health() -> dict[str, str | bool]:
        """Return service health for Docker healthchecks."""
        model = ModelRouter().get_model()
        return {"status": "ok", "provider": model.provider, "model": model.model_name, "model_ready": True}

    return app


app = create_app()
