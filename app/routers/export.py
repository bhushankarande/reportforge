"""Report export endpoints."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

router = APIRouter(prefix="/jobs/{job_id}", tags=["exports"])


@router.get("/export/{format}")
async def export_report(job_id: str, format: str) -> PlainTextResponse:
    """Return an export artifact placeholder."""
    if format not in {"markdown", "pdf", "docx"}:
        raise HTTPException(status_code=400, detail="unsupported export format")
    return PlainTextResponse(f"Report {job_id} export: {format}")
