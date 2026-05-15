"""Report writer agent with stricter evidence grounding."""

from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import dataclass
import json
from json import JSONDecodeError
import math
import re
from typing import Any

from app.logging_config import get_logger
from schemas.agent_outputs import WriterInput, WriterOutput
from schemas.sources import Claim, VerificationStatus
from orchestration.cost_tracking import CostTrackingModel
from tools.llm.model_router import ModelRouter

logger = get_logger(__name__)

CITATION_PATTERN = re.compile(r"\[([A-Za-z0-9_-]+)\]")
MAX_EVIDENCE_CHARS = 24_000
MAX_SELECTED_EVIDENCE = 18
MIN_SECTION_WORDS = 180
CLAIM_SUPPORT_THRESHOLD = 0.22


@dataclass(frozen=True)
class EvidenceChunk:
    """A compact cited evidence sentence used for section writing."""

    chunk_id: str
    text: str
    citation_key: str
    score: float = 0.0

    @property
    def citation_token(self) -> str:
        """Return citation key with brackets."""
        return f"[{self.citation_key}]"


@dataclass(frozen=True)
class WriterDraft:
    """Parsed model draft before validation."""

    section_title: str
    paragraphs: list[str]
    claims: list[str]
    sources_used: list[str]


class ReportWriterAgent:
    """
    Draft one report section at a time from evidence.

    This version does not fabricate source IDs, does not repair missing citations
    by attaching nearby citations, and does not mark a claim supported merely
    because a citation marker exists.
    """

    STOPWORDS = {
        "about",
        "above",
        "after",
        "again",
        "against",
        "also",
        "because",
        "been",
        "being",
        "between",
        "both",
        "could",
        "does",
        "each",
        "from",
        "have",
        "into",
        "more",
        "most",
        "only",
        "other",
        "over",
        "same",
        "some",
        "such",
        "than",
        "that",
        "their",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "under",
        "using",
        "very",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "with",
        "would",
        "section",
        "report",
        "evidence",
    }

    BOILERPLATE_FRAGMENTS = (
        "request a quote",
        "products in interest",
        "want to hear more",
        "linear inverted pendulum",
        "smart motion devices",
        "ball balancing",
        "mobile autonomous robot",
        "cookie policy",
        "privacy policy",
        "terms of use",
        "all rights reserved",
        "subscribe to our newsletter",
        "share this article",
        "skip to content",
        "accept cookies",
        "manage cookies",
    )

    def __init__(self, router: ModelRouter | None = None) -> None:
        """Initialize writer with model router."""
        self.router = router or ModelRouter()
        self.model = CostTrackingModel(self.router.get_model())
        self.last_diagnostics: dict[str, Any] = {}

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

        section_plan = self._extract_section_plan(writer_input.rolling_summary or "")
        topic_terms = self._topic_terms(
            " ".join(
                [
                    writer_input.section_title,
                    writer_input.rolling_summary or "",
                    " ".join(section_plan.get("research_questions", [])) if section_plan else "",
                    " ".join(section_plan.get("required_evidence", [])) if section_plan else "",
                ]
            )
        )

        all_chunks = self._evidence_chunks(writer_input.evidence)
        selected_chunks = self._select_evidence_chunks(all_chunks, topic_terms)
        sources_used = self._sources_from_chunks(selected_chunks)

        self.last_diagnostics = {
            "input_evidence_items": len(writer_input.evidence),
            "parsed_evidence_chunks": len(all_chunks),
            "selected_evidence_chunks": len(selected_chunks),
            "sources_used": sources_used,
            "section_plan_found": bool(section_plan),
        }

        if not selected_chunks:
            content = self._insufficient_evidence_content(writer_input.section_title)
            claims = self._extract_claims(
                job_id=writer_input.job_id,
                section_title=writer_input.section_title,
                content=content,
                evidence_by_key={},
            )
            return WriterOutput(
                section_title=writer_input.section_title,
                content=content,
                claims=claims,
                sources_used=[],
            )

        evidence_context = self._build_evidence_context(selected_chunks)
        prompt = self._build_prompt(
            writer_input=writer_input,
            evidence_context=evidence_context,
            selected_chunks=selected_chunks,
            section_plan=section_plan,
        )

        response = self.model(prompt).text
        draft = self._parse_writer_draft(response, writer_input.section_title)
        evidence_by_key = self._evidence_by_key(selected_chunks)

        content: str | None = None
        if draft is not None:
            content = self._validated_content_from_draft(
                draft=draft,
                section_title=writer_input.section_title,
                allowed_citation_keys=set(sources_used),
                evidence_by_key=evidence_by_key,
            )

        if content is None:
            content = self._compose_grounded_section(
                section_title=writer_input.section_title,
                chunks=selected_chunks,
                section_plan=section_plan,
            )

        content = self._ensure_section_quality(
            content=content,
            section_title=writer_input.section_title,
            chunks=selected_chunks,
            section_plan=section_plan,
        )

        claims = self._extract_claims(
            job_id=writer_input.job_id,
            section_title=writer_input.section_title,
            content=content,
            evidence_by_key=evidence_by_key,
        )

        supported_sources = self._sources_from_claims(claims)

        logger.info(
            "writer_completed",
            job_id=writer_input.job_id,
            section_title=writer_input.section_title,
            claims=len(claims),
            sources_used=supported_sources,
        )

        return WriterOutput(
            section_title=writer_input.section_title,
            content=content,
            claims=claims,
            sources_used=supported_sources,
        )

    def _build_prompt(
        self,
        writer_input: WriterInput,
        evidence_context: str,
        selected_chunks: list[EvidenceChunk],
        section_plan: dict[str, Any],
    ) -> str:
        """Build a strict JSON-only section generation prompt."""
        allowed_citations = ", ".join(chunk.citation_token for chunk in selected_chunks)
        minimum_source_count = self._minimum_source_diversity(selected_chunks)
        target_words = self._target_words(section_plan)
        plan_text = json.dumps(section_plan, ensure_ascii=False) if section_plan else "{}"

        return f"""
You are ReportForge WriterAgent.
Return one valid JSON object only. No markdown fences. No commentary.

Job: {writer_input.job_id}
Section title: {writer_input.section_title}
Target words: approximately {target_words}
Allowed citations: {allowed_citations}

Section plan JSON:
{plan_text}

Rules:
- Use only the evidence below.
- Do not introduce facts that are not directly supported by the evidence.
- Every factual sentence must include at least one allowed citation key.
- Do not use a citation key unless the sentence is directly supported by that evidence.
- Use evidence from at least {minimum_source_count} distinct citation keys when that many relevant sources are available.
- If evidence is insufficient, say so clearly and do not invent details.
- Prefer 3-6 focused paragraphs sized to the target word count.
- Do not stop after a few sentences when more cited evidence is available.
- Do not use bullets unless the section plan explicitly requires a list.

Return this JSON schema:
{{
  "section_title": "{writer_input.section_title}",
  "paragraphs": ["paragraph with citations"],
  "claims": [
    {{"text": "claim text", "citation_keys": ["CitationKey"]}}
  ],
  "sources_used": ["CitationKey"]
}}

Evidence:
{evidence_context}
""".strip()

    @staticmethod
    def _extract_section_plan(rolling_summary: str) -> dict[str, Any]:
        """
        Extract optional section plan JSON from rolling_summary.

        Compatibility bridge: PlannerAgent.section_plan_for_writer(...) can be
        passed into WriterInput.rolling_summary until WriterInput has a proper
        section_plan field.
        """
        if not rolling_summary:
            return {}

        json_text = ReportWriterAgent._extract_first_json_object(rolling_summary)
        if not json_text:
            return {}

        try:
            data = json.loads(json_text)
        except JSONDecodeError:
            return {}

        if isinstance(data, dict) and isinstance(data.get("section_plan"), dict):
            return data["section_plan"]

        if isinstance(data, dict):
            return data

        return {}

    @staticmethod
    def _parse_writer_draft(response: str, section_title: str) -> WriterDraft | None:
        """Parse strict writer JSON. Raw prose is not accepted."""
        json_text = ReportWriterAgent._extract_first_json_object(response)
        if not json_text:
            return None

        try:
            payload = json.loads(json_text)
        except JSONDecodeError:
            return None

        if not isinstance(payload, dict):
            return None

        raw_paragraphs = payload.get("paragraphs")
        if raw_paragraphs is None and isinstance(payload.get("content"), str):
            raw_paragraphs = [payload["content"]]

        paragraphs = ReportWriterAgent._string_list(raw_paragraphs)
        if not paragraphs:
            return None

        claims = []
        raw_claims = payload.get("claims")
        if isinstance(raw_claims, list):
            for item in raw_claims:
                if isinstance(item, dict):
                    text = item.get("text") or item.get("claim")
                else:
                    text = item
                if text and str(text).strip():
                    claims.append(str(text).strip())

        sources_used = ReportWriterAgent._string_list(payload.get("sources_used"))
        sources_used = [source.strip("[]") for source in sources_used]

        return WriterDraft(
            section_title=str(payload.get("section_title") or section_title),
            paragraphs=paragraphs,
            claims=claims,
            sources_used=ReportWriterAgent._dedupe_strings(sources_used),
        )

    @classmethod
    def _validated_content_from_draft(
        cls,
        draft: WriterDraft,
        section_title: str,
        allowed_citation_keys: set[str],
        evidence_by_key: dict[str, str],
    ) -> str | None:
        """Keep only model sentences that are cited and evidence-supported."""
        validated_paragraphs: list[str] = []

        for paragraph in draft.paragraphs:
            kept_sentences: list[str] = []
            for sentence in cls._citation_aware_sentences(paragraph):
                citation_keys = cls._citation_keys(sentence)
                if not citation_keys:
                    continue
                if not set(citation_keys).issubset(allowed_citation_keys):
                    continue
                support_score = cls._support_score(sentence, citation_keys, evidence_by_key)
                if support_score >= CLAIM_SUPPORT_THRESHOLD:
                    kept_sentences.append(cls._normalize_sentence(sentence))

            if kept_sentences:
                validated_paragraphs.append(" ".join(kept_sentences))

        if not validated_paragraphs:
            return None

        return cls._ensure_heading("\n\n".join(validated_paragraphs), section_title)

    @classmethod
    def _evidence_chunks(cls, evidence: list[str]) -> list[EvidenceChunk]:
        """Convert raw evidence strings into cited sentence-level chunks."""
        chunks: list[EvidenceChunk] = []
        seen: set[tuple[str, str]] = set()
        total_chars = 0

        for item_index, item in enumerate(evidence, start=1):
            if not item:
                continue

            if total_chars >= MAX_EVIDENCE_CHARS:
                break

            raw_item = item[: max(0, MAX_EVIDENCE_CHARS - total_chars)]
            total_chars += len(raw_item)

            citation_keys = cls._citation_keys(raw_item)
            if not citation_keys:
                continue

            clean_text = cls._clean_evidence_text(raw_item)
            sentences = cls._split_evidence_sentences(clean_text)

            for citation_key in citation_keys:
                for sentence_index, sentence in enumerate(sentences, start=1):
                    key = (citation_key, sentence.lower())
                    if key in seen:
                        continue
                    seen.add(key)
                    chunks.append(
                        EvidenceChunk(
                            chunk_id=f"E{item_index}_{sentence_index}_{citation_key}",
                            text=sentence,
                            citation_key=citation_key,
                        )
                    )

        return chunks

    @classmethod
    def _select_evidence_chunks(
        cls,
        chunks: list[EvidenceChunk],
        topic_terms: set[str],
    ) -> list[EvidenceChunk]:
        """Rank and select compact evidence while preserving source diversity."""
        scored: list[EvidenceChunk] = []

        for chunk in chunks:
            score = cls._chunk_score(chunk.text, topic_terms)
            scored.append(
                EvidenceChunk(
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    citation_key=chunk.citation_key,
                    score=score,
                )
            )

        if topic_terms:
            scored = [chunk for chunk in scored if chunk.score > 0]

        if not scored:
            scored = [
                EvidenceChunk(
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    citation_key=chunk.citation_key,
                    score=cls._chunk_score(chunk.text, set()),
                )
                for chunk in chunks
            ]

        grouped: dict[str, list[EvidenceChunk]] = defaultdict(list)
        for chunk in sorted(scored, key=lambda item: item.score, reverse=True):
            grouped[chunk.citation_key].append(chunk)

        source_order = sorted(
            grouped,
            key=lambda citation_key: grouped[citation_key][0].score,
            reverse=True,
        )

        selected: list[EvidenceChunk] = []
        source_counts: dict[str, int] = defaultdict(int)
        max_per_source = max(3, math.ceil(MAX_SELECTED_EVIDENCE / max(len(source_order), 1)))

        while len(selected) < MAX_SELECTED_EVIDENCE:
            added_this_round = False
            for citation_key in source_order:
                if len(selected) >= MAX_SELECTED_EVIDENCE:
                    break
                if source_counts[citation_key] >= max_per_source:
                    continue
                source_chunks = grouped[citation_key]
                if source_counts[citation_key] >= len(source_chunks):
                    continue
                selected.append(source_chunks[source_counts[citation_key]])
                source_counts[citation_key] += 1
                added_this_round = True
            if not added_this_round:
                break

        return selected

    @classmethod
    def _chunk_score(cls, text: str, topic_terms: set[str]) -> float:
        """Score an evidence sentence against section/topic terms."""
        tokens = cls._content_terms(text)
        if not tokens:
            return 0.0

        if not topic_terms:
            return min(len(tokens) / 60.0, 1.0)

        overlap = tokens.intersection(topic_terms)
        coverage = len(overlap) / max(len(topic_terms), 1)
        density = len(overlap) / max(len(tokens), 1)
        specificity = min(len(tokens) / 45.0, 1.0)
        number_bonus = 0.1 if re.search(r"\d", text) else 0.0

        return round((0.55 * coverage) + (0.25 * density * 5) + (0.15 * specificity) + number_bonus, 4)

    @staticmethod
    def _build_evidence_context(chunks: list[EvidenceChunk]) -> str:
        """Build a compact prompt context from selected evidence chunks."""
        lines: list[str] = []
        used = 0

        for chunk in chunks:
            line = f"- {chunk.chunk_id} | {chunk.citation_token} | {chunk.text}"
            if used + len(line) > MAX_EVIDENCE_CHARS:
                break
            lines.append(line)
            used += len(line)

        return "\n".join(lines)

    @staticmethod
    def _evidence_by_key(chunks: list[EvidenceChunk]) -> dict[str, str]:
        """Group selected evidence text by citation key."""
        grouped: dict[str, list[str]] = defaultdict(list)
        for chunk in chunks:
            grouped[chunk.citation_key].append(chunk.text)
        return {key: " ".join(values) for key, values in grouped.items()}

    @classmethod
    def _compose_grounded_section(
        cls,
        section_title: str,
        chunks: list[EvidenceChunk],
        section_plan: dict[str, Any],
    ) -> str:
        """Compose conservative fallback prose using evidence text directly."""
        if not chunks:
            return cls._insufficient_evidence_content(section_title)

        target_words = cls._target_words(section_plan)
        min_words = cls._minimum_section_words(section_plan)
        target_chunk_count = max(6, min(len(chunks), math.ceil(target_words / 35)))
        selected = chunks[:target_chunk_count]
        paragraphs: list[str] = []

        current: list[str] = []
        for chunk in selected:
            current.append(cls._ensure_period(f"{chunk.text} {chunk.citation_token}"))
            if len(current) >= 2:
                paragraphs.append(" ".join(current))
                current = []
            if len(" ".join(paragraphs).split()) >= min_words:
                break

        if current:
            paragraphs.append(" ".join(current))

        if len(" ".join(paragraphs).split()) < min_words:
            for chunk in chunks[len(selected) :]:
                paragraphs.append(cls._ensure_period(f"{chunk.text} {chunk.citation_token}"))
                if len(" ".join(paragraphs).split()) >= min_words:
                    break

        return cls._ensure_heading("\n\n".join(paragraphs), section_title)

    @classmethod
    def _ensure_section_quality(
        cls,
        content: str,
        section_title: str,
        chunks: list[EvidenceChunk],
        section_plan: dict[str, Any],
    ) -> str:
        """Fallback if generated content is too thin or citation-free."""
        body = re.sub(r"^## .*$", "", content, flags=re.MULTILINE).strip()
        word_count = len(body.split())
        citations = cls._citation_keys(body)
        available_sources = cls._sources_from_chunks(chunks)
        minimum_sources = cls._minimum_source_diversity(chunks)
        min_words = cls._minimum_section_words(section_plan)

        has_enough_source_diversity = len(set(citations)) >= minimum_sources

        if word_count >= min_words and citations and has_enough_source_diversity:
            return content

        fallback = cls._compose_grounded_section(section_title, chunks, section_plan)
        fallback_body = re.sub(r"^## .*$", "", fallback, flags=re.MULTILINE).strip()
        fallback_citations = cls._citation_keys(fallback_body)
        fallback_has_enough_sources = len(set(fallback_citations)) >= min(
            minimum_sources,
            len(available_sources),
        )

        if fallback_has_enough_sources or len(fallback_body.split()) >= word_count:
            return fallback

        return content

    @classmethod
    def _extract_claims(
        cls,
        job_id: str,
        section_title: str,
        content: str,
        evidence_by_key: dict[str, str],
    ) -> list[Claim]:
        """Extract claim objects and verify them against cited evidence text."""
        body = re.sub(r"^## .*$", "", content, flags=re.MULTILINE).strip()

        if "Insufficient evidence" in body:
            return [
                Claim(
                    id=f"{job_id}-{cls._slug(section_title)}-claim-1",
                    section_id=section_title,
                    text="Insufficient evidence was supplied for this section.",
                    source_ids=[],
                    verification_status=VerificationStatus.UNVERIFIED,
                    confidence=0.2,
                )
            ]

        sentences = [
            sentence
            for sentence in cls._citation_aware_sentences(body)
            if cls._has_claim_text(sentence)
        ]

        claims: list[Claim] = []

        for index, sentence in enumerate(sentences, start=1):
            citation_keys = cls._citation_keys(sentence)
            support_score = cls._support_score(sentence, citation_keys, evidence_by_key)
            supported = bool(citation_keys) and support_score >= CLAIM_SUPPORT_THRESHOLD

            claims.append(
                Claim(
                    id=f"{job_id}-{cls._slug(section_title)}-claim-{index}",
                    section_id=section_title,
                    text=sentence,
                    source_ids=citation_keys if supported else [],
                    verification_status=VerificationStatus.SUPPORTED
                    if supported
                    else VerificationStatus.UNVERIFIED,
                    confidence=round(min(0.95, max(0.2, support_score)), 2)
                    if supported
                    else 0.2,
                )
            )

        if not claims:
            claims.append(
                Claim(
                    id=f"{job_id}-{cls._slug(section_title)}-claim-1",
                    section_id=section_title,
                    text="No verifiable claim could be extracted from this section.",
                    source_ids=[],
                    verification_status=VerificationStatus.UNVERIFIED,
                    confidence=0.2,
                )
            )

        return claims

    @classmethod
    def _support_score(
        cls,
        sentence: str,
        citation_keys: list[str],
        evidence_by_key: dict[str, str],
    ) -> float:
        """Estimate whether a cited sentence is supported by cited evidence text."""
        if not citation_keys:
            return 0.0

        claim_terms = cls._content_terms(CITATION_PATTERN.sub("", sentence))
        if not claim_terms:
            return 0.0

        evidence_text = " ".join(evidence_by_key.get(key, "") for key in citation_keys)
        evidence_terms = cls._content_terms(evidence_text)
        if not evidence_terms:
            return 0.0

        claim_numbers = set(re.findall(r"\b\d+(?:\.\d+)?%?\b", sentence))
        evidence_numbers = set(re.findall(r"\b\d+(?:\.\d+)?%?\b", evidence_text))
        if claim_numbers and not claim_numbers.issubset(evidence_numbers):
            return 0.0

        overlap = claim_terms.intersection(evidence_terms)
        coverage = len(overlap) / max(len(claim_terms), 1)
        density = len(overlap) / max(len(evidence_terms), 1)

        return round(min(1.0, (0.85 * coverage) + (0.15 * math.sqrt(density))), 4)

    @classmethod
    def _clean_evidence_text(cls, text: str) -> str:
        """Clean evidence while preserving factual content, figures, and metrics."""
        text = CITATION_PATTERN.sub("", text)
        text = re.sub(r"\r\n?", "\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"\s+", " ", text)

        for fragment in cls.BOILERPLATE_FRAGMENTS:
            text = re.sub(re.escape(fragment) + r".*?(?=[.!?]|$)", " ", text, flags=re.IGNORECASE)

        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _split_evidence_sentences(cls, text: str) -> list[str]:
        """Split source evidence into useful sentence chunks."""
        candidates = re.split(r"(?<=[.!?])\s+", text)
        sentences: list[str] = []
        seen: set[str] = set()

        for candidate in candidates:
            sentence = cls._normalize_sentence(candidate)
            if not cls._is_useful_evidence_sentence(sentence):
                continue
            key = sentence.lower()
            if key in seen:
                continue
            seen.add(key)
            sentences.append(cls._ensure_period(sentence))

        return sentences

    @classmethod
    def _is_useful_evidence_sentence(cls, sentence: str) -> bool:
        """Return True if sentence looks like useful evidence."""
        if not 45 <= len(sentence) <= 650:
            return False

        lower = sentence.lower()
        if any(fragment in lower for fragment in cls.BOILERPLATE_FRAGMENTS):
            return False

        words = re.findall(r"[A-Za-z][A-Za-z-]+", sentence)
        if len(words) < 8:
            return False

        alpha_ratio = sum(
            char.isalpha() or char.isspace() or char in ".,;:!?()[]%-/"
            for char in sentence
        ) / max(len(sentence), 1)

        return alpha_ratio >= 0.65

    @classmethod
    def _citation_aware_sentences(cls, text: str) -> list[str]:
        """Split text into sentences while preserving citation markers."""
        raw_sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", text)
            if sentence.strip()
        ]

        merged: list[str] = []

        for sentence in raw_sentences:
            citation_only = re.fullmatch(r"(\[[A-Za-z0-9_-]+\])[.!?]?", sentence)
            if citation_only and merged:
                merged[-1] = f"{merged[-1]} {citation_only.group(1)}"
                continue
            merged.append(sentence)

        return merged

    @staticmethod
    def _citation_keys(text: str) -> list[str]:
        """Extract citation keys without brackets."""
        keys = [match.group(1) for match in CITATION_PATTERN.finditer(text)]
        return list(OrderedDict.fromkeys(keys))

    @staticmethod
    def _sources_from_chunks(chunks: list[EvidenceChunk]) -> list[str]:
        """Return unique citation keys from chunks."""
        return list(OrderedDict.fromkeys(chunk.citation_key for chunk in chunks))

    @staticmethod
    def _minimum_source_diversity(chunks: list[EvidenceChunk]) -> int:
        """Return minimum citation diversity expected for selected evidence."""
        source_count = len(ReportWriterAgent._sources_from_chunks(chunks))
        if source_count <= 1:
            return 1
        return min(3, source_count)

    @staticmethod
    def _sources_from_claims(claims: list[Claim]) -> list[str]:
        """Return unique supported source IDs from claims."""
        keys: list[str] = []
        for claim in claims:
            keys.extend(claim.source_ids)
        return list(OrderedDict.fromkeys(keys))

    @classmethod
    def _topic_terms(cls, text: str) -> set[str]:
        """Extract dynamic section/topic terms."""
        return {
            token
            for token in cls._tokens(text)
            if len(token) >= 2 and token not in cls.STOPWORDS
        }

    @classmethod
    def _content_terms(cls, text: str) -> set[str]:
        """Extract content terms used for rough support checking."""
        return {
            token
            for token in cls._tokens(text)
            if len(token) >= 3 and token not in cls.STOPWORDS
        }

    @staticmethod
    def _tokens(text: str) -> list[str]:
        """Tokenize text into normalized terms."""
        return [
            token.strip(".-_").lower()
            for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9+#._-]*", text)
            if token.strip(".-_")
        ]

    @staticmethod
    def _extract_first_json_object(text: str) -> str | None:
        """Extract first balanced JSON object from text."""
        start = text.find("{")
        if start < 0:
            return None

        depth = 0
        in_string = False
        escape = False

        for index in range(start, len(text)):
            char = text[index]

            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]

        return None

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        """Normalize a model field into a list of strings."""
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if not isinstance(value, list):
            text = str(value).strip()
            return [text] if text else []

        items: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                items.append(text)
        return ReportWriterAgent._dedupe_strings(items)

    @staticmethod
    def _dedupe_strings(items: list[str]) -> list[str]:
        """Deduplicate strings while preserving order."""
        seen: set[str] = set()
        output: list[str] = []
        for item in items:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            output.append(item)
        return output

    @staticmethod
    def _ensure_heading(content: str, section_title: str) -> str:
        """Ensure generated content starts with the section heading."""
        if re.match(r"^#{1,3}\s+", content.strip()):
            return content.strip()
        return f"## {section_title}\n\n{content.strip()}"

    @staticmethod
    def _normalize_sentence(sentence: str) -> str:
        """Normalize one sentence."""
        return re.sub(r"\s+", " ", sentence).strip(" -•\n\t")

    @staticmethod
    def _ensure_period(sentence: str) -> str:
        """Ensure sentence ends cleanly."""
        sentence = sentence.strip()
        if not sentence:
            return sentence
        if sentence[-1] not in ".!?":
            return f"{sentence}."
        return sentence

    @staticmethod
    def _lowercase_lead(sentence: str) -> str:
        """Lowercase first character for embedding evidence mid-sentence."""
        sentence = sentence.strip()
        if not sentence:
            return sentence
        return sentence[0].lower() + sentence[1:]

    @staticmethod
    def _has_claim_text(sentence: str) -> bool:
        """Return whether sentence contains claim text beyond citations."""
        without_citations = CITATION_PATTERN.sub("", sentence).strip()
        return bool(re.search(r"[A-Za-z]{3,}", without_citations))

    @staticmethod
    def _insufficient_evidence_content(section_title: str) -> str:
        """Return safe insufficient-evidence section content."""
        return (
            f"## {section_title}\n\n"
            "Insufficient evidence was supplied for this section. "
            "No evidence-backed claims should be made until relevant cited sources are available."
        )

    @staticmethod
    def _target_words(section_plan: dict[str, Any]) -> int:
        """Return section target words from plan when available."""
        try:
            target_words = int(section_plan.get("target_words", 220))
        except (TypeError, ValueError):
            target_words = 220
        return max(180, min(target_words, 900))

    @staticmethod
    def _minimum_section_words(section_plan: dict[str, Any]) -> int:
        """Return minimum acceptable section length for the requested depth."""
        target_words = ReportWriterAgent._target_words(section_plan)
        return max(MIN_SECTION_WORDS, min(target_words, int(target_words * 0.65)))

    @staticmethod
    def _slug(text: str) -> str:
        """Create stable slug for claim IDs."""
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
        return slug or "section"
