"""Shared FastAPI helpers for stable API behavior."""

from __future__ import annotations

from fastapi import HTTPException

from schemas.sources import Source


JOB_NOT_FOUND = "job not found"


def require_job(manager, job_id: str):
    """Return a job or raise the stable API 404."""
    try:
        return manager.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=JOB_NOT_FOUND) from exc


def require_sections(manager, job_id: str):
    """Return report sections or raise the stable API 404."""
    require_job(manager, job_id)
    return manager.list_sections(job_id)


def require_sources(manager, job_id: str):
    """Return report sources or raise the stable API 404."""
    require_job(manager, job_id)
    return manager.list_sources(job_id)


def require_traces(manager, job_id: str):
    """Return report traces or raise the stable API 404."""
    require_job(manager, job_id)
    return manager.list_traces(job_id)


def append_sources(manager, job_id: str, sources: list[Source]) -> list[Source]:
    """Append sources to a job and persist the merged list."""
    existing = require_sources(manager, job_id)
    merged = [*existing, *sources]
    manager.sources_by_job[job_id] = merged
    manager.store.save_sources(job_id, merged)
    return merged
