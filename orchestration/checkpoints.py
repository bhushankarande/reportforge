"""JSON checkpoint persistence."""

import json
from pathlib import Path

from orchestration.state import WorkflowState


class CheckpointStore:
    """Save and load report workflow checkpoints."""

    def __init__(self, root: str | Path = "storage/checkpoints") -> None:
        """Initialize checkpoint storage."""
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, state: WorkflowState) -> Path:
        """Persist state to a JSON checkpoint."""
        path = self.root / f"{state.job_id}.json"
        path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load(self, job_id: str) -> WorkflowState | None:
        """Load a workflow state if it exists."""
        path = self.root / f"{job_id}.json"
        if not path.exists():
            return None
        return WorkflowState.model_validate(json.loads(path.read_text(encoding="utf-8")))
