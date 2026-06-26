"""Section mutation endpoints."""

from fastapi import APIRouter, HTTPException

from app.services.api_support import require_job, require_sections
from app.services.job_registry import manager

router = APIRouter(prefix="/jobs/{job_id}", tags=["sections"])


@router.get("/sections")
async def list_sections(job_id: str) -> list[dict[str, object]]:
    """List report sections."""
    return [section.model_dump() for section in require_sections(manager, job_id)]


@router.post("/regenerate-section", status_code=202)
async def regenerate_section(job_id: str, section_id: str, feedback: str = "") -> dict[str, str]:
    """Start section-level regeneration."""
    require_job(manager, job_id)
    try:
        section = manager.regenerate_section(job_id, section_id, feedback)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="section not found") from exc
    return {
        "job_id": job_id,
        "section_id": section.id,
        "status": section.status,
        "feedback": feedback,
    }


@router.post("/approve")
async def approve_job(job_id: str) -> dict[str, str]:
    """Approve a human-in-the-loop review gate."""
    require_job(manager, job_id)
    job = manager.approve(job_id)
    return {"job_id": job_id, "status": job.status.value}


@router.post("/retry", status_code=202)
async def retry_job(job_id: str) -> dict[str, str]:
    """Retry a failed job by rerunning the live pipeline."""
    require_job(manager, job_id)
    manager.retry(job_id)
    return {"job_id": job_id, "status": "retrying"}
