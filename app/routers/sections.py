"""Section mutation endpoints."""

from fastapi import APIRouter, HTTPException

from app.services.job_registry import manager

router = APIRouter(prefix="/jobs/{job_id}", tags=["sections"])


@router.get("/sections")
async def list_sections(job_id: str) -> list[dict[str, object]]:
    """List report sections."""
    if job_id not in manager.jobs:
        raise HTTPException(status_code=404, detail="job not found")
    return [section.model_dump() for section in manager.list_sections(job_id)]


@router.post("/regenerate-section", status_code=202)
async def regenerate_section(job_id: str, section_id: str, feedback: str = "") -> dict[str, str]:
    """Start section-level regeneration."""
    if job_id not in manager.jobs:
        raise HTTPException(status_code=404, detail="job not found")
    try:
        section = manager.regenerate_section(job_id, section_id, feedback)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="section not found") from exc
    return {"job_id": job_id, "section_id": section.id, "status": section.status, "feedback": feedback}


@router.post("/approve")
async def approve_job(job_id: str) -> dict[str, str]:
    """Approve a human-in-the-loop checkpoint."""
    if job_id not in manager.jobs:
        raise HTTPException(status_code=404, detail="job not found")
    job = manager.approve(job_id)
    return {"job_id": job_id, "status": job.status.value}


@router.post("/retry", status_code=202)
async def retry_job(job_id: str) -> dict[str, str]:
    """Retry a failed job from its last checkpoint."""
    if job_id not in manager.jobs:
        raise HTTPException(status_code=404, detail="job not found")
    manager.retry(job_id)
    return {"job_id": job_id, "status": "retrying"}
