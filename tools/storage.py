"""Storage directory management."""

from pathlib import Path

from app.config import get_settings


class StorageManager:
    """Create and resolve ReportForge storage paths."""

    def __init__(self, root: str | Path | None = None) -> None:
        """Initialize the storage manager."""
        self.root = Path(root or get_settings().storage_dir)

    def ensure(self) -> None:
        """Create all runtime storage subdirectories."""
        for name in ["uploads", "reports", "charts", "indexes", "llm_logs"]:
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str, area: str) -> Path:
        """Return a report-scoped directory for an artifact area."""
        path = self.root / area / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path
