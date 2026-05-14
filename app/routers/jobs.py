"""Job API endpoints."""

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse

from app.services.job_registry import manager
from schemas.api import CreateJobRequest, CreateJobResponse, JobProgress

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=CreateJobResponse, status_code=202)
async def create_job(request: CreateJobRequest, background_tasks: BackgroundTasks) -> CreateJobResponse:
    """Submit a new report job."""
    response = manager.create_job(request)
    background_tasks.add_task(manager.execute, response.job_id)
    return response


@router.get("/{job_id}")
async def get_job(job_id: str) -> dict[str, object]:
    """Return a full job snapshot."""
    if job_id not in manager.jobs:
        raise HTTPException(status_code=404, detail="job not found")
    return manager.get_job(job_id).model_dump()


@router.get("/{job_id}/progress", response_model=JobProgress)
async def get_progress(job_id: str) -> JobProgress:
    """Return lightweight job progress."""
    if job_id not in manager.jobs:
        raise HTTPException(status_code=404, detail="job not found")
    return manager.progress(job_id)


@router.get("/{job_id}/progress/stream")
async def stream_progress(job_id: str) -> StreamingResponse:
    """Stream job progress updates as server-sent events."""
    if job_id not in manager.jobs:
        raise HTTPException(status_code=404, detail="job not found")

    async def event_stream() -> AsyncIterator[str]:
        last_payload = ""
        for _ in range(300):
            payload = manager.progress(job_id).model_dump_json()
            if payload != last_payload:
                yield f"event: progress\ndata: {payload}\n\n"
                last_payload = payload
            if manager.jobs[job_id].status.value in {"completed", "failed", "awaiting_approval"}:
                break
            await asyncio.sleep(2)
        yield f"event: done\ndata: {json.dumps({'job_id': job_id})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/{job_id}/sources")
async def list_sources(job_id: str) -> list[dict[str, object]]:
    """List report sources."""
    if job_id not in manager.jobs:
        raise HTTPException(status_code=404, detail="job not found")
    return [source.model_dump() for source in manager.list_sources(job_id)]


@router.get("/{job_id}/traces")
async def list_traces(job_id: str) -> list[dict[str, object]]:
    """List agent traces."""
    if job_id not in manager.jobs:
        raise HTTPException(status_code=404, detail="job not found")
    return [trace.model_dump() for trace in manager.list_traces(job_id)]
