"""Job API endpoints."""

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from agents.document_reader_agent import DocumentParseError
from app.services.api_support import append_sources, require_job, require_sources, require_traces
from app.services.job_registry import manager
from app.services.uploads import UploadDocument, UploadService
from schemas.api import CreateJobRequest, CreateJobResponse, JobProgress

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=CreateJobResponse, status_code=202)
async def create_job(
    request: CreateJobRequest, background_tasks: BackgroundTasks
) -> CreateJobResponse:
    """Submit a new report job."""
    response = manager.create_job(request)
    background_tasks.add_task(manager.execute, response.job_id)
    return response


@router.get("/{job_id}")
async def get_job(job_id: str) -> dict[str, object]:
    """Return a full job snapshot."""
    return require_job(manager, job_id).model_dump()


@router.get("/{job_id}/progress", response_model=JobProgress)
async def get_progress(job_id: str) -> JobProgress:
    """Return lightweight job progress."""
    require_job(manager, job_id)
    return manager.progress(job_id)


@router.get("/{job_id}/progress/stream")
async def stream_progress(job_id: str) -> StreamingResponse:
    """Stream job progress updates as server-sent events."""
    require_job(manager, job_id)

    async def event_stream() -> AsyncIterator[str]:
        last_payload = ""
        for _ in range(300):
            payload = manager.progress(job_id).model_dump_json()
            if payload != last_payload:
                yield f"event: progress\ndata: {payload}\n\n"
                last_payload = payload
            if manager.get_job(job_id).status.value in {"completed", "failed", "awaiting_approval"}:
                break
            await asyncio.sleep(2)
        yield f"event: done\ndata: {json.dumps({'job_id': job_id})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/{job_id}/sources")
async def list_sources(job_id: str) -> list[dict[str, object]]:
    """List report sources."""
    return [source.model_dump() for source in require_sources(manager, job_id)]


@router.get("/{job_id}/traces")
async def list_traces(job_id: str) -> list[dict[str, object]]:
    """List agent traces."""
    return [trace.model_dump() for trace in require_traces(manager, job_id)]


@router.post("/{job_id}/uploads", status_code=201)
async def upload_documents(job_id: str, files: list[UploadFile] = File(...)) -> dict[str, object]:
    """Upload documents and normalize them into sources/evidence."""
    require_job(manager, job_id)
    documents = [
        UploadDocument(filename=file.filename or "upload.txt", content=await file.read())
        for file in files
    ]
    try:
        result = UploadService().ingest(
            job_id=job_id,
            documents=documents,
            existing_sources=require_sources(manager, job_id),
        )
    except (DocumentParseError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    append_sources(manager, job_id, result.sources)
    return {
        "job_id": job_id,
        "files": result.files,
        "source_ids": result.source_ids,
        "chunks_indexed": result.chunks_indexed,
    }
