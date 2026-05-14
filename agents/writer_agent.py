"""Report writer agent."""

import json
import re
from collections import OrderedDict
from json import JSONDecodeError

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
            "do not invent facts, and follow a concise business-report tone. "
            "Return JSON only with keys: section_title, content, claims, sources_used. "
            "claims must be a list of claim text strings."
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
        response = self.model(prompt).text
        content = self._content_from_model_response(response, writer_input.section_title)
        if content is None:
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
            "Write 3-6 substantial paragraphs for this section when evidence is available.\n"
            "Use only the citation keys present in the evidence.\n"
            "Every factual sentence must end with one or more source citations.\n"
            f"Evidence:\n{evidence_text}\n"
        )

    @staticmethod
    def _content_from_model_response(response: str, section_title: str) -> str | None:
        """Extract Markdown content from a model response when it is useful."""
        stripped = response.strip()
        if not stripped or stripped.startswith("["):
            return None
        json_payload = ReportWriterAgent._extract_json_object(stripped)
        if json_payload is not None:
            try:
                data = json.loads(json_payload)
            except JSONDecodeError:
                data = {}
            content = data.get("content") if isinstance(data, dict) else None
            if isinstance(content, str) and content.strip():
                return ReportWriterAgent._prune_to_cited_sentences(
                    ReportWriterAgent._ensure_heading(content.strip(), section_title)
                )
        if len(stripped.split()) < 20:
            return None
        return ReportWriterAgent._prune_to_cited_sentences(
            ReportWriterAgent._ensure_heading(stripped, section_title)
        )

    @staticmethod
    def _extract_json_object(text: str) -> str | None:
        """Return the first JSON object found in a model response."""
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.IGNORECASE | re.MULTILINE).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return text[start : end + 1]
        return None

    @staticmethod
    def _ensure_heading(content: str, section_title: str) -> str:
        """Ensure generated content starts with the section heading."""
        if re.match(r"^#{1,3}\s+", content):
            return content
        return f"## {section_title}\n\n{content}"

    @staticmethod
    def _prune_to_cited_sentences(content: str) -> str:
        """Keep headings and citation-bearing factual sentences."""
        lines = content.splitlines()
        output: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if output and output[-1] != "":
                    output.append("")
                continue
            if stripped.startswith("#"):
                output.append(stripped)
                continue
            sentences = [
                sentence
                for sentence in ReportWriterAgent._citation_aware_sentences(stripped)
                if CITATION_PATTERN.search(sentence)
            ]
            if sentences:
                output.append(" ".join(sentences))
                output.append("")
        return "\n".join(output).strip()

    @staticmethod
    def _citation_aware_sentences(text: str) -> list[str]:
        """Split sentences while keeping standalone citations attached to prior text."""
        raw_sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", text) if sentence.strip()]
        merged: list[str] = []
        for sentence in raw_sentences:
            leading_citation = re.match(r"^(\[[A-Za-z0-9_-]+\])\s+(.+)$", sentence)
            if leading_citation and merged:
                merged[-1] = f"{merged[-1]} {leading_citation.group(1)}"
                merged.append(leading_citation.group(2))
                continue
            if CITATION_PATTERN.fullmatch(sentence) and merged:
                merged[-1] = f"{merged[-1]} {sentence}"
                continue
            merged.append(sentence)
        return merged

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
            for sentence in ReportWriterAgent._citation_aware_sentences(body)
            if sentence.strip() and not CITATION_PATTERN.fullmatch(sentence.strip())
        ]
        if not sentences:
            sentences = [body] if body else ["Insufficient evidence was supplied."]
        claims: list[Claim] = []
        for index, sentence in enumerate(sentences, start=1):
            sentence_sources = ReportWriterAgent._dedupe_sources(sentence)
            source_ids = sentence_sources or sources_used
            if source_ids == ["SourceID"] and "Insufficient evidence" in sentence:
                source_ids = []
            status = VerificationStatus.SUPPORTED if source_ids else VerificationStatus.UNVERIFIED
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
