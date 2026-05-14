"""Cost dashboard endpoints."""

from fastapi import APIRouter

from app.services.job_registry import manager

router = APIRouter(prefix="/costs", tags=["costs"])


@router.get("/summary")
async def costs_summary() -> dict[str, float | int]:
    """Return zero-cost testing summary."""
    return manager.cost_summary()
