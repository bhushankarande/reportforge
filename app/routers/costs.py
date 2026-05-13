"""Cost dashboard endpoints."""

from fastapi import APIRouter

router = APIRouter(prefix="/costs", tags=["costs"])


@router.get("/summary")
async def costs_summary() -> dict[str, float | int]:
    """Return zero-cost testing summary."""
    return {"job_count": 0, "total_tokens": 0, "actual_cost_usd": 0.0, "estimated_kimi_cost_usd": 0.0}
