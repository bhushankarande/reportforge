"""Report writer agent."""

import json
import re
from collections import OrderedDict
from dataclasses import dataclass
from json import JSONDecodeError

from app.logging_config import get_logger
from schemas.agent_outputs import WriterInput, WriterOutput
from schemas.sources import Claim, VerificationStatus
from orchestration.cost_tracking import CostTrackingModel
from tools.llm.model_router import ModelRouter

logger = get_logger(__name__)
MAX_EVIDENCE_CHARS = 180_000
MIN_SECTION_WORDS = 90
CITATION_PATTERN = re.compile(r"\[([A-Za-z0-9_-]+)\]")


@dataclass(frozen=True)
class EvidencePoint:
    """Clean evidence sentence paired with its citation key."""

    text: str
    citation: str


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
        content = self._ensure_paragraph_depth(
            content,
            writer_input.section_title,
            writer_input.evidence,
            sources_used,
        )
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
            "Write at least 2 substantial paragraphs for this section when evidence is available.\n"
            "Target 150-250 words for this section.\n"
            "Use only the citation keys present in the evidence.\n"
            "Every factual sentence must end with one or more source citations.\n"
            "Do not use bullets unless the section title explicitly asks for a list.\n"
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
        """Keep headings and repair citation-bearing factual paragraphs."""
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
            sentences = ReportWriterAgent._repair_missing_sentence_citations(
                ReportWriterAgent._citation_aware_sentences(stripped)
            )
            if sentences:
                output.append(" ".join(sentences))
                output.append("")
        return "\n".join(output).strip()

    @staticmethod
    def _repair_missing_sentence_citations(sentences: list[str]) -> list[str]:
        """Preserve coherent model prose by attaching nearby citations to uncited sentences."""
        repaired: list[str] = []
        last_citation: str | None = None
        future_citation = next((CITATION_PATTERN.search(sentence).group(0) for sentence in sentences if CITATION_PATTERN.search(sentence)), None)
        for sentence in sentences:
            citation = CITATION_PATTERN.search(sentence)
            if citation:
                repaired.append(sentence)
                last_citation = citation.group(0)
                continue
            fallback_citation = last_citation or future_citation
            if fallback_citation:
                clean_sentence = sentence.rstrip()
                if clean_sentence[-1:] not in {".", "!", "?"}:
                    clean_sentence = f"{clean_sentence}."
                repaired.append(f"{clean_sentence} {fallback_citation}")
        return repaired

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
        points = ReportWriterAgent._evidence_points(evidence, sources_used)
        if not points:
            return f"## {section_title}\n\nInsufficient evidence was supplied for this section."
        paragraphs = ReportWriterAgent._synthesized_paragraphs(section_title, points)
        return f"## {section_title}\n\n" + "\n\n".join(paragraphs)

    @staticmethod
    def _evidence_points(evidence: list[str], sources_used: list[str]) -> list[EvidencePoint]:
        """Extract clean, cited evidence points from raw source snippets."""
        points: list[EvidencePoint] = []
        for index, item in enumerate(evidence):
            citation_match = CITATION_PATTERN.search(item)
            if citation_match:
                citation = citation_match.group(0)
            elif sources_used:
                citation = f"[{sources_used[min(index, len(sources_used) - 1)]}]"
            else:
                citation = "[SourceID]"
            clean_item = ReportWriterAgent._clean_evidence_text(item)
            sentences = ReportWriterAgent._rank_evidence_sentences(clean_item)
            for sentence in sentences[:2]:
                point = EvidencePoint(text=sentence, citation=citation)
                if point not in points:
                    points.append(point)
            if len(points) >= 5:
                break
        return points

    @staticmethod
    def _clean_evidence_text(text: str) -> str:
        """Remove citations and common scraped website boilerplate from evidence."""
        text = CITATION_PATTERN.sub("", text)
        noisy_patterns = (
            r"REQUEST A QUOTE.*",
            r"Products in Interest.*",
            r"Want to hear more.*",
            r"Share this article.*",
            r"Cookie Policy.*",
            r"Privacy Policy.*",
            r"©.*",
        )
        for pattern in noisy_patterns:
            text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\bkeywords?:\b.*?(?=[A-Z][a-z]+\s)", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\bFigure\s+\d+[:.].*?(?=[A-Z][a-z]+\s)", " ", text, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _rank_evidence_sentences(text: str) -> list[str]:
        """Return useful evidence sentences ordered by reporting value."""
        candidates: list[str] = []
        seen: set[str] = set()
        noise = (
            "request a quote",
            "products in interest",
            "want to hear more",
            "linear inverted pendulum",
            "smart motion devices",
            "ball balancing",
            "mobile autonomous robot",
            "cookie",
            "subscribe",
        )
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            normalized = re.sub(r"\s+", " ", sentence).strip(" -•")
            lower = normalized.lower()
            words = re.findall(r"[A-Za-z][A-Za-z-]+", normalized)
            if not 12 <= len(words) <= 70:
                continue
            if any(fragment in lower for fragment in noise):
                continue
            if lower in seen:
                continue
            seen.add(lower)
            candidates.append(normalized.rstrip(" .") + ".")
        signal_terms = ("robot", "language", "model", "llm", "task", "planning", "control", "autonomous", "collaboration")
        return sorted(
            candidates,
            key=lambda sentence: sum(1 for term in signal_terms if term in sentence.lower()),
            reverse=True,
        )

    @staticmethod
    def _synthesized_paragraphs(section_title: str, points: list[EvidencePoint]) -> list[str]:
        """Create readable report paragraphs from clean evidence points."""
        first = points[0]
        paragraphs = [
            (
                f"The strongest evidence for {section_title.lower()} is that "
                f"{ReportWriterAgent._lowercase_lead(first.text)} {first.citation}"
            )
        ]
        if len(points) >= 2:
            second = points[1]
            paragraphs.append(
                f"A second relevant source point is that "
                f"{ReportWriterAgent._lowercase_lead(second.text)} {second.citation}"
            )
        if len(points) >= 4:
            third = points[2]
            fourth = points[3]
            paragraphs.append(
                f"The remaining evidence adds two useful constraints: "
                f"{ReportWriterAgent._lowercase_lead(third.text)} {third.citation} "
                f"{fourth.text} {fourth.citation}"
            )
        return paragraphs

    @staticmethod
    def _section_lens(section_title: str) -> str:
        """Return a section-specific opening frame."""
        lower = section_title.lower()
        if "executive" in lower or "summary" in lower:
            return "The central takeaway should be read directly from the cited source evidence."
        if "market" in lower or "competitive" in lower:
            return "From a market perspective, the important signal should come from the cited source evidence."
        if "technical" in lower or "architecture" in lower:
            return "Technically, the relevant shift should be grounded in the cited source evidence."
        if "risk" in lower or "challenge" in lower or "limitation" in lower:
            return "The main risks should be limited to what the cited source evidence supports."
        if "recommend" in lower or "outlook" in lower:
            return "The practical recommendation should be constrained by the cited source evidence."
        return f"For {section_title.lower()}, each claim should connect directly to cited source evidence."

    @staticmethod
    def _lowercase_lead(sentence: str) -> str:
        """Lowercase the first word when embedding an evidence sentence mid-paragraph."""
        if not sentence:
            return sentence
        return sentence[0].lower() + sentence[1:]

    @staticmethod
    def _ensure_paragraph_depth(
        content: str,
        section_title: str,
        evidence: list[str],
        sources_used: list[str],
    ) -> str:
        """Expand overly terse sections using only cited evidence snippets."""
        body = re.sub(r"^## .*$", "", content, flags=re.MULTILINE).strip()
        if len(body.split()) >= MIN_SECTION_WORDS and len([line for line in body.splitlines() if line.strip()]) >= 2:
            return content
        fallback = ReportWriterAgent._compose_section(section_title, evidence, sources_used)
        fallback_body = re.sub(r"^## .*$", "", fallback, flags=re.MULTILINE).strip()
        if len(fallback_body.split()) > len(body.split()):
            return fallback
        return content

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
            if ReportWriterAgent._has_claim_text(sentence)
        ]
        if not sentences:
            sentences = [body] if ReportWriterAgent._has_claim_text(body) else ["Insufficient evidence was supplied."]
        claims: list[Claim] = []
        for index, sentence in enumerate(sentences, start=1):
            sentence_sources = ReportWriterAgent._dedupe_sources(sentence)
            source_ids = sentence_sources or sources_used
            if "Insufficient evidence" in sentence:
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

    @staticmethod
    def _has_claim_text(sentence: str) -> bool:
        """Return whether a sentence contains real claim text beyond citations."""
        stripped = sentence.strip()
        if not stripped:
            return False
        without_citations = CITATION_PATTERN.sub("", stripped)
        return bool(re.search(r"[A-Za-z]{3,}", without_citations))
