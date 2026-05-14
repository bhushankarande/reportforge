"""FastAPI dependency providers."""

from collections.abc import Generator

from sqlalchemy.orm import Session

from app.database import SessionLocal
from orchestration.state import WorkflowState
from tools.llm.model_router import ModelRouter, RoutedModel


def get_db_session() -> Generator[Session, None, None]:
    """Yield a SQLite database session for request-scoped work."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_model_router() -> ModelRouter:
    """Return the active model router."""
    return ModelRouter()


def get_active_model(router: ModelRouter | None = None) -> RoutedModel:
    """Return the active routed model wrapper."""
    return (router or ModelRouter()).get_model()


def get_workflow_state(job_id: str) -> WorkflowState:
    """Return an initial workflow state for dependency-injected handlers."""
    return WorkflowState(job_id=job_id)
