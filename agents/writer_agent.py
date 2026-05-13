"""Report writer agent."""

from schemas.agent_outputs import WriterInput, WriterOutput
from schemas.sources import Claim, VerificationStatus
from tools.llm.model_router import ModelRouter


class ReportWriterAgent:
    """Draft one report section at a time from approved evidence."""

    def __init__(self, router: ModelRouter | None = None) -> None:
        """Initialize writer with model router."""
        self.router = router or ModelRouter()

    def write(self, writer_input: WriterInput) -> WriterOutput:
        """Write a sourced section using only supplied evidence."""
        self.router.get_model("gemini")
        evidence_text = " ".join(writer_input.evidence) or "No evidence supplied."
        content = f"## {writer_input.section_title}\n\n{evidence_text} [SourceID]"
        claim = Claim(
            id=f"{writer_input.job_id}-{writer_input.section_title}-claim-1",
            section_id=writer_input.section_title,
            text=evidence_text,
            source_ids=["SourceID"] if writer_input.evidence else [],
            verification_status=VerificationStatus.SUPPORTED if writer_input.evidence else VerificationStatus.UNVERIFIED,
            confidence=0.8 if writer_input.evidence else 0.2,
        )
        return WriterOutput(section_title=writer_input.section_title, content=content, claims=[claim])
