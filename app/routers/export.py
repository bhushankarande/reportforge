"""Report export endpoints."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.services.job_registry import manager
from tools.export.docx import write_docx
from tools.export.pdf import write_pdf

router = APIRouter(prefix="/jobs/{job_id}", tags=["exports"])


@router.get("/export/{format}")
async def export_report(job_id: str, format: str) -> Response:
    """Return a report export artifact."""
    if job_id not in manager.jobs:
        raise HTTPException(status_code=404, detail="job not found")
    if format not in {"markdown", "pdf", "docx"}:
        raise HTTPException(status_code=400, detail="unsupported export format")
    try:
        markdown = manager.export_markdown(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if format == "markdown":
        return Response(markdown, media_type="text/markdown")
    output_dir = "storage/reports"
    job = manager.get_job(job_id)
    if format == "pdf":
        path = write_pdf(markdown, f"{output_dir}/{job_id}.pdf")
        return Response(
            path.read_bytes(),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{job.topic}.pdf"'},
        )
    path = write_docx(markdown, f"{output_dir}/{job_id}.docx")
    return Response(
        path.read_bytes(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{job.topic}.docx"'},
    )
