"""Report writer agent."""

import re
from collections import OrderedDict

from app.logging_config import get_logger
from schemas.agent_outputs import WriterInput, WriterOutput
from schemas.sources import Claim, VerificationStatus
from orchestration.cost_tracking import CostTrackingModel
from tools.llm.model_router import ModelRouter

logger = get_logger(__name__)
MAX_EVIDENCE_CHARS = 180_000
CITATION_PATTERN = re.compile(r"\[([A-Za-z0-9_-]+)\]")


class ReportWriterAgent:
    """Draft one report section at a time from approved evidence."""

    def __init__(self, router: ModelRouter | None = None) -> None:
        """Initialize writer with model router."""
        self.router = router or ModelRouter()
        self.sys_prompt = (
            "You are ReportForge WriterAgent. Write one section at a time. "
            "Use only supplied evidence, cite sources with [CitationKey] format, "
            "do not invent facts, follow the requested tone, and return structured content "
            "with SECTION_TITLE, markdown content, CLAIMS, and SOURCES_USED."
        )
        self.model = CostTrackingModel(self.router.get_model())

    def write(self, writer_input: WriterInput) -> WriterOutput:
        """Backward-compatible wrapper around run."""
        return self.run(writer_input)

    def run(self, writer_input: WriterInput) -> WriterOutput:
        """Write a sourced section using only supplied evidence."""
        logger.info(
            "writer_started",
            job_id=writer_input.job_id,
            section_title=writer_input.section_title,
            evidence_items=len(writer_input.evidence),
        )
        evidence_text = self._build_evidence_context(writer_input.evidence)
        sources_used = self._dedupe_sources(evidence_text) or ["SourceID"]
        prompt = self._build_prompt(writer_input, evidence_text)
        self.model(prompt)
        content = self._compose_section(writer_input.section_title, writer_input.evidence, sources_used)
        claims = self._extract_claims(writer_input.job_id, writer_input.section_title, content, sources_used)
        logger.info(
            "writer_completed",
            job_id=writer_input.job_id,
            section_title=writer_input.section_title,
            claims=len(claims),
            sources_used=sources_used,
        )
        return WriterOutput(
            section_title=writer_input.section_title,
            content=content,
            claims=claims,
            sources_used=sources_used,
        )

    def _build_prompt(self, writer_input: WriterInput, evidence_text: str) -> str:
        """Build the section generation prompt with rolling-summary context."""
        return (
            f"{self.sys_prompt}\n"
            f"Job: {writer_input.job_id}\n"
            f"Section: {writer_input.section_title}\n"
            f"Rolling summary: {writer_input.rolling_summary or 'None'}\n"
            f"Evidence:\n{evidence_text}\n"
        )

    @staticmethod
    def _build_evidence_context(evidence: list[str]) -> str:
        """Build bounded evidence context under the 180K prompt budget."""
        bounded: list[str] = []
        used = 0
        for item in evidence:
            remaining = MAX_EVIDENCE_CHARS - used
            if remaining <= 0:
                break
            chunk = item[:remaining]
            bounded.append(chunk)
            used += len(chunk)
        return "\n\n".join(bounded) if bounded else "No evidence supplied."

    @staticmethod
    def _dedupe_sources(text: str) -> list[str]:
        """Extract and deduplicate bracket citation keys from text."""
        keys = [match.group(1) for match in CITATION_PATTERN.finditer(text)]
        return list(OrderedDict.fromkeys(keys))

    @staticmethod
    def _compose_section(section_title: str, evidence: list[str], sources_used: list[str]) -> str:
        """Compose deterministic Markdown content from approved evidence."""
        if not evidence:
            return f"## {section_title}\n\nInsufficient evidence was supplied for this section."
        paragraphs: list[str] = []
        for index, item in enumerate(evidence[:3]):
            citation_match = CITATION_PATTERN.search(item)
            citation = citation_match.group(0) if citation_match else f"[{sources_used[min(index, len(sources_used) - 1)]}]"
            clean_item = CITATION_PATTERN.sub("", item)
            clean_item = re.sub(r"\s+", " ", clean_item).strip()
            if not clean_item:
                continue
            snippet = clean_item[:420].rstrip(" ,;:")
            paragraphs.append(f"{snippet}. {citation}")
        body = "\n\n".join(paragraphs) if paragraphs else "Insufficient evidence was supplied for this section."
        return f"## {section_title}\n\n{body}"

    @staticmethod
    def _extract_claims(
        job_id: str,
        section_title: str,
        content: str,
        sources_used: list[str],
    ) -> list[Claim]:
        """Extract claim objects from generated Markdown sentences."""
        body = re.sub(r"^## .*$", "", content, flags=re.MULTILINE).strip()
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", body)
            if sentence.strip() and not CITATION_PATTERN.fullmatch(sentence.strip())
        ]
        if not sentences:
            sentences = [body] if body else ["Insufficient evidence was supplied."]
        source_ids = sources_used if sources_used != ["SourceID"] else ["SourceID"]
        claims: list[Claim] = []
        for index, sentence in enumerate(sentences, start=1):
            status = VerificationStatus.SUPPORTED if source_ids and "Insufficient evidence" not in sentence else VerificationStatus.UNVERIFIED
            claims.append(
                Claim(
                    id=f"{job_id}-{section_title}-claim-{index}",
                    section_id=section_title,
                    text=sentence,
                    source_ids=source_ids if status == VerificationStatus.SUPPORTED else [],
                    verification_status=status,
                    confidence=0.8 if status == VerificationStatus.SUPPORTED else 0.2,
                )
            )
        return claims
