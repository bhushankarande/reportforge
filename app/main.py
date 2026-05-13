"""FastAPI entrypoint for ReportForge."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.logging_config import configure_logging
from app.routers import costs, export, jobs, sections
from tools.storage import StorageManager


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize storage, logging, and database tables."""
    configure_logging()
    StorageManager().ensure()
    init_db()
    yield


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
    return app


app = create_app()
