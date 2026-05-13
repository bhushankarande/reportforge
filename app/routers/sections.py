"""Section mutation endpoints."""

from fastapi import APIRouter

router = APIRouter(prefix="/jobs/{job_id}", tags=["sections"])


@router.get("/sections")
async def list_sections(job_id: str) -> list[dict[str, object]]:
    """List report sections."""
    return []


@router.post("/regenerate-section", status_code=202)
async def regenerate_section(job_id: str, section_id: str, feedback: str = "") -> dict[str, str]:
    """Start section-level regeneration."""
    return {"job_id": job_id, "section_id": section_id, "status": "queued", "feedback": feedback}


@router.post("/approve")
async def approve_job(job_id: str) -> dict[str, str]:
    """Approve a human-in-the-loop checkpoint."""
    return {"job_id": job_id, "status": "approved"}


@router.post("/retry", status_code=202)
async def retry_job(job_id: str) -> dict[str, str]:
    """Retry a failed job from its last checkpoint."""
    return {"job_id": job_id, "status": "retrying"}
