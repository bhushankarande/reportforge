"""Report job queue and status management."""

from datetime import datetime, timezone
from uuid import uuid4

from schemas.api import CreateJobRequest, CreateJobResponse, JobProgress
from schemas.reports import ReportJob, ReportStatus


class JobManager:
    """In-memory MVP job manager with session isolation hooks."""

    def __init__(self) -> None:
        """Initialize empty job manager."""
        self.jobs: dict[str, ReportJob] = {}

    def create_job(self, request: CreateJobRequest, *, session_id: str = "anonymous") -> CreateJobResponse:
        """Create a pending report job."""
        job_id = str(uuid4())
        job = ReportJob(
            id=job_id,
            topic=request.topic,
            type=request.type,
            depth=request.depth,
            status=ReportStatus.PENDING,
            created_at=datetime.now(timezone.utc).isoformat(),
            session_id=session_id,
        )
        self.jobs[job_id] = job
        return CreateJobResponse(job_id=job_id, status=job.status)

    def progress(self, job_id: str) -> JobProgress:
        """Return progress for a job."""
        job = self.jobs[job_id]
        return JobProgress(job_id=job.id, status=job.status, current_step=job.status.value)
