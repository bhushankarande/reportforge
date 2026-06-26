"""Report export endpoints."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from agents.formatter_agent import FormatterAgent
from app.services.api_support import require_job, require_sources
from app.services.job_registry import manager
from tools.export.report import ExportBlockedError, ExportFormatError

router = APIRouter(prefix="/jobs/{job_id}", tags=["exports"])
formatter = FormatterAgent()


@router.get("/export/{format}")
async def export_report(job_id: str, format: str) -> Response:
    """Return a report export artifact."""
    job = require_job(manager, job_id)
    try:
        artifact = formatter.export_artifact(
            job,
            require_sources(manager, job_id),
            "storage/reports",
            export_format=format,
        )
    except ExportFormatError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ExportBlockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    headers = {}
    if artifact.format != "md":
        headers["Content-Disposition"] = f'attachment; filename="{artifact.filename}"'

    return Response(
        artifact.path.read_bytes(),
        media_type=artifact.media_type,
        headers=headers,
    )
