"""Retention cleanup for report-scoped runtime artifacts."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)


def cleanup_old_artifacts(storage_dir: str | Path, days: int = 7) -> list[Path]:
    """Delete files older than the retention window and return removed paths."""
    root = Path(storage_dir)
    removed: list[Path] = []
    if not root.exists():
        return removed

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if modified >= cutoff:
            continue
        try:
            path.unlink()
            removed.append(path)
            logger.info("artifact_removed", path=str(path))
        except OSError as exc:
            logger.warning("artifact_cleanup_failed", path=str(path), error=str(exc))
    return removed
