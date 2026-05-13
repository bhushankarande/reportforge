"""Workflow state models."""

from pydantic import BaseModel, ConfigDict, Field


class WorkflowState(BaseModel):
    """Serializable workflow state."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    current_step: str = "pending"
    completed_steps: list[str] = Field(default_factory=list)
    failed: bool = False

    def mark_completed(self, step: str) -> None:
        """Mark a workflow step complete."""
        self.current_step = step
        if step not in self.completed_steps:
            self.completed_steps.append(step)
