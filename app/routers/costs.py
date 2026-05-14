"""Cost dashboard endpoints."""

from fastapi import APIRouter

from app.services.job_registry import manager
from tools.llm.quota_manager import QuotaManager

router = APIRouter(prefix="/costs", tags=["costs"])


@router.get("/summary")
async def costs_summary() -> dict[str, float | int]:
    """Return zero-cost testing summary."""
    return manager.cost_summary()


@router.get("/quota")
async def quota_status() -> dict[str, int]:
    """Return remaining free-tier provider quota."""
    return QuotaManager().status()
