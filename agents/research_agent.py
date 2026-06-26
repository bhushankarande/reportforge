"""
Research agent using URL-backed sources.

This agent avoids fake evidence by default. It deduplicates URLs, tracks source
failures, scores topic relevance, and stores real extracted source text.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.logging_config import get_logger
from schemas.agent_outputs import ResearchOutput
from schemas.sources import EvidenceChunk, Source
from tools.llm.model_router import ModelRouter
from tools.rag.evidence_pipeline import EvidencePipeline, EvidencePipelineResult, RawEvidence
from tools.rag.hybrid_retriever import HybridRetriever
from tools.search.url_fetcher import URLFetchError, fetch_url_text

logger = get_logger(__name__)


class ResearchAgentError(RuntimeError):
    """Raised when the research agent cannot collect usable evidence."""


@dataclass(frozen=True)
class SourceFailure:
    """A URL that failed during collection or extraction."""

    url: str
    reason: str
    detail: str = ""


@dataclass(frozen=True)
class ScoredSentence:
    """A sentence with a relevance score."""

    text: str
    score: float


class ResearchAgent:
    """Collect external URL sources with metadata and relevance scores."""

    MIN_SOURCE_CHARS = 500
    MAX_RAW_TEXT_CHARS = 30_000
    MAX_EXCERPT_CHARS = 2_500
    MAX_SUMMARY_CHARS = 900
    MAX_SELECTED_SENTENCES = 8

    TRACKING_PARAMS = {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
    }

    STOPWORDS = {
        "about",
        "after",
        "again",
        "against",
        "being",
        "between",
        "could",
        "every",
        "from",
        "have",
        "into",
        "more",
        "most",
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
    }

    BOILERPLATE_FRAGMENTS = (
        "cookie policy",
        "privacy policy",
        "terms of use",
        "all rights reserved",
        "subscribe to our newsletter",
        "sign up for our newsletter",
        "share this article",
        "skip to content",
        "skip to main content",
        "follow us on",
        "facebook",
        "linkedin",
        "twitter",
        "x twitter",
        "instagram",
        "accept cookies",
        "manage cookies",
    )

    def __init__(
        self,
        router: ModelRouter | None = None,
        *,
        allow_mock_sources: bool = False,
        raise_on_total_failure: bool = True,
        min_relevance_score: float = 0.08,
    ) -> None:
        """Initialize the research agent."""
        self.router = router or ModelRouter()
        self.allow_mock_sources = allow_mock_sources
        self.raise_on_total_failure = raise_on_total_failure
        self.min_relevance_score = min_relevance_score
        self.last_failures: list[SourceFailure] = []
        self.last_evidence_chunks: list[EvidenceChunk] = []
        self.last_retriever: HybridRetriever | None = None

    def research(
        self,
        job_id: str,
        topic: str,
        urls: list[str] | None = None,
    ) -> ResearchOutput:
        """
        Collect URL-backed research sources.

        If URLs are supplied and none produce usable evidence, this raises by
        default instead of fabricating mock research.
        """
        self.last_failures = []
        self.last_evidence_chunks = []
        self.last_retriever = None
        prepared_urls = self._prepare_urls(urls or [])

        if not prepared_urls:
            logger.warning("research_no_urls_supplied", job_id=job_id, topic=topic)
            if self.allow_mock_sources:
                return self._mock_output(job_id=job_id, topic=topic)
            return ResearchOutput(sources=[])

        evidence = self._evidence_from_urls(job_id=job_id, topic=topic, urls=prepared_urls)
        sources = evidence.sources
        self.last_evidence_chunks = evidence.chunks
        self.last_retriever = evidence.retriever

        if not sources:
            message = (
                f"No usable URL-backed sources collected for topic={topic!r}. "
                f"Failures: {self._format_failures()}"
            )
            logger.warning(
                "research_no_usable_sources",
                job_id=job_id,
                topic=topic,
                failures=[failure.__dict__ for failure in self.last_failures],
            )
            if self.raise_on_total_failure:
                raise ResearchAgentError(message)
            return ResearchOutput(sources=[])

        logger.info(
            "research_url_sources_collected",
            job_id=job_id,
            topic=topic,
            sources=len(sources),
            failures=len(self.last_failures),
        )
        return ResearchOutput(sources=sources)

    def _evidence_from_urls(
        self,
        job_id: str,
        topic: str,
        urls: list[str],
    ) -> EvidencePipelineResult:
        """Fetch user-provided URLs into normalized evidence records."""
        evidence_items: list[RawEvidence] = []
        topic_terms = self._topic_terms(topic)

        for index, url in enumerate(urls, start=1):
            citation_key = self._citation_key(url=url, index=index)
            try:
                title, text = fetch_url_text(url)
            except URLFetchError as exc:
                self._record_failure(url, "fetch_failed", str(exc))
                continue
            except Exception as exc:
                self._record_failure(url, "unexpected_fetch_error", str(exc))
                continue

            text = self._clean_source_text(text)
            quality_failure = self._source_quality_failure(text)
            if quality_failure:
                self._record_failure(url, "low_quality_source", quality_failure)
                continue

            excerpt = self._topic_excerpt(
                text=text,
                topic_terms=topic_terms,
                max_chars=self.MAX_EXCERPT_CHARS,
            )
            if not excerpt:
                self._record_failure(
                    url,
                    "no_relevant_excerpt",
                    "Could not extract useful topic-relevant sentences.",
                )
                continue

            relevance_score = self._relevance_score(
                full_text=text,
                excerpt=excerpt,
                topic_terms=topic_terms,
            )
            if relevance_score < self.min_relevance_score:
                self._record_failure(
                    url,
                    "low_relevance",
                    f"Score {relevance_score:.3f} below threshold {self.min_relevance_score:.3f}",
                )
                continue

            summary = self._extractive_summary(excerpt=excerpt, max_chars=self.MAX_SUMMARY_CHARS)
            evidence_items.append(
                RawEvidence(
                    source_type="web",
                    title=title or self._fallback_title(url),
                    url=url,
                    text=text,
                    summary=summary,
                    relevance_score=relevance_score,
                    citation_key=citation_key,
                )
            )

        return EvidencePipeline(job_id).ingest(evidence_items)

    def _record_failure(self, url: str, reason: str, detail: str = "") -> None:
        """Store and log a source failure."""
        failure = SourceFailure(url=url, reason=reason, detail=detail)
        self.last_failures.append(failure)
        logger.warning("research_url_failed", url=url, reason=reason, detail=detail)

    def _prepare_urls(self, urls: list[str]) -> list[str]:
        """Normalize and deduplicate URLs before fetching."""
        prepared: list[str] = []
        seen: set[str] = set()

        for raw_url in urls:
            if not raw_url or not raw_url.strip():
                continue
            try:
                canonical_url = self._canonicalize_url(raw_url)
            except ValueError as exc:
                self._record_failure(raw_url, "invalid_url", str(exc))
                continue

            if canonical_url in seen:
                continue

            seen.add(canonical_url)
            prepared.append(canonical_url)

        return prepared

    @classmethod
    def _canonicalize_url(cls, url: str) -> str:
        """Canonicalize URL for deduplication and cleaner fetching."""
        cleaned = url.strip()
        parts = urlsplit(cleaned)

        if parts.scheme.lower() not in {"http", "https"}:
            raise ValueError("Only http and https URLs are allowed.")

        if not parts.netloc:
            raise ValueError("URL is missing a domain.")

        query_pairs = parse_qsl(parts.query, keep_blank_values=True)
        clean_query_pairs = [
            (key, value)
            for key, value in query_pairs
            if key.lower() not in cls.TRACKING_PARAMS and not key.lower().startswith("utm_")
        ]
        clean_query = urlencode(clean_query_pairs, doseq=True)
        path = parts.path or "/"

        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, clean_query, ""))

    @staticmethod
    def _clean_source_text(text: str) -> str:
        """Clean extracted source text without destroying useful content."""
        cleaned = re.sub(r"\r\n?", "\n", text)
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = re.sub(r"(?i)<svg.*?</svg>", " ", cleaned, flags=re.DOTALL)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

    @classmethod
    def _source_quality_failure(cls, text: str) -> str:
        """Return a failure reason if source text is not useful."""
        if not text:
            return "No text extracted."
        if len(text) < cls.MIN_SOURCE_CHARS:
            return f"Extracted text is too short: {len(text)} characters."

        lower = text.lower()
        bad_markers = [
            "enable javascript",
            "access denied",
            "verify you are human",
            "checking your browser",
            "captcha",
            "cloudflare",
            "subscribe to continue",
            "sign in to continue",
        ]
        for marker in bad_markers:
            if marker in lower:
                return f"Page appears blocked or not readable: {marker}"

        alpha_chars = sum(char.isalpha() or char.isspace() for char in text)
        alpha_ratio = alpha_chars / max(len(text), 1)
        if alpha_ratio < 0.55:
            return f"Text has low alphabetic ratio: {alpha_ratio:.2f}"

        return ""

    @classmethod
    def _topic_terms(cls, topic: str) -> set[str]:
        """Extract meaningful topic terms, including short technical acronyms."""
        tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9+#.-]*", topic.lower())
        return {
            token.strip(".-")
            for token in tokens
            if len(token.strip(".-")) >= 2 and token.strip(".-") not in cls.STOPWORDS
        }

    @classmethod
    def _topic_excerpt(cls, text: str, topic_terms: set[str], *, max_chars: int) -> str:
        """Return a compact evidence excerpt biased toward the requested topic."""
        sentences = cls._split_sentences(text)
        scored_sentences: list[ScoredSentence] = []

        for sentence in sentences:
            normalized = cls._normalize_sentence(sentence)
            if not cls._is_useful_sentence(normalized):
                continue

            score = cls._sentence_relevance_score(sentence=normalized, topic_terms=topic_terms)
            if score > 0:
                scored_sentences.append(ScoredSentence(text=normalized, score=score))

        if not scored_sentences:
            useful_sentences = [
                cls._normalize_sentence(sentence)
                for sentence in sentences
                if cls._is_useful_sentence(cls._normalize_sentence(sentence))
            ]
            fallback = " ".join(useful_sentences[: cls.MAX_SELECTED_SENTENCES])
            return fallback[:max_chars].strip()

        scored_sentences.sort(key=lambda item: item.score, reverse=True)
        selected = scored_sentences[: cls.MAX_SELECTED_SENTENCES]
        selected_texts = cls._restore_original_order(
            original_sentences=sentences,
            selected_sentences=[item.text for item in selected],
        )
        excerpt = " ".join(selected_texts)
        return excerpt[:max_chars].strip()

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split text into rough sentences."""
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return []
        return re.split(r"(?<=[.!?])\s+", text)

    @classmethod
    def _sentence_relevance_score(cls, sentence: str, topic_terms: set[str]) -> float:
        """Score a sentence using exact-ish token overlap with topic terms."""
        if not topic_terms:
            return 0.1

        sentence_tokens = {
            token.strip(".-")
            for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9+#.-]*", sentence.lower())
        }
        if not sentence_tokens:
            return 0.0

        matched_terms = topic_terms.intersection(sentence_tokens)
        if not matched_terms:
            return 0.0

        coverage = len(matched_terms) / len(topic_terms)
        density = len(matched_terms) / max(len(sentence_tokens), 1)
        length_bonus = 0.1 if 80 <= len(sentence) <= 300 else 0.0
        return coverage + min(density * 3.0, 0.5) + length_bonus

    @classmethod
    def _relevance_score(cls, full_text: str, excerpt: str, topic_terms: set[str]) -> float:
        """Compute a simple relevance score from topic coverage and text length."""
        if not topic_terms:
            return 0.35

        full_tokens = cls._text_tokens(full_text)
        excerpt_tokens = cls._text_tokens(excerpt)
        full_coverage = len(topic_terms.intersection(full_tokens)) / len(topic_terms)
        excerpt_coverage = len(topic_terms.intersection(excerpt_tokens)) / len(topic_terms)
        term_hits = sum(1 for term in topic_terms if term in excerpt_tokens)
        density = term_hits / max(len(excerpt_tokens), 1)
        text_length_score = min(math.log10(max(len(full_text), 1)) / 5.0, 1.0)
        score = (
            0.45 * excerpt_coverage
            + 0.30 * full_coverage
            + 0.15 * min(density * 20.0, 1.0)
            + 0.10 * text_length_score
        )
        return round(max(0.0, min(score, 1.0)), 3)

    @staticmethod
    def _text_tokens(text: str) -> set[str]:
        """Tokenize text into normalized terms."""
        return {
            token.strip(".-")
            for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9+#.-]*", text.lower())
            if token.strip(".-")
        }

    @classmethod
    def _extractive_summary(cls, excerpt: str, *, max_chars: int) -> str:
        """Build an honest extractive summary."""
        sentences = cls._split_sentences(excerpt)
        useful = [
            cls._normalize_sentence(sentence)
            for sentence in sentences
            if cls._is_useful_sentence(cls._normalize_sentence(sentence))
        ]
        summary = " ".join(useful[:4]) or excerpt
        return summary[:max_chars].strip()

    @classmethod
    def _is_useful_sentence(cls, sentence: str) -> bool:
        """Return whether scraped text is useful evidence rather than page chrome."""
        if not sentence:
            return False
        if not 45 <= len(sentence) <= 650:
            return False

        lower = sentence.lower()
        if any(fragment in lower for fragment in cls.BOILERPLATE_FRAGMENTS):
            return False

        words = re.findall(r"[A-Za-z][A-Za-z-]+", sentence)
        if len(words) < 8:
            return False

        alpha_ratio = sum(
            char.isalpha() or char.isspace() or char in ".,;:!?()[]%-" for char in sentence
        ) / max(len(sentence), 1)
        if alpha_ratio < 0.70:
            return False

        uppercase_words = [word for word in words if len(word) > 3 and word.isupper()]
        return len(uppercase_words) <= max(3, len(words) // 4)

    @staticmethod
    def _normalize_sentence(sentence: str) -> str:
        """Normalize a sentence."""
        return re.sub(r"\s+", " ", sentence).strip(" -•\n\t")

    @classmethod
    def _restore_original_order(
        cls,
        original_sentences: list[str],
        selected_sentences: list[str],
    ) -> list[str]:
        """Keep selected evidence sentences in their original order."""
        selected_set = set(selected_sentences)
        ordered: list[str] = []
        seen: set[str] = set()

        for sentence in original_sentences:
            normalized = cls._normalize_sentence(sentence)
            if normalized in selected_set and normalized not in seen:
                ordered.append(normalized)
                seen.add(normalized)

        return ordered

    @staticmethod
    def _citation_key(url: str, index: int) -> str:
        """Create a readable citation key from domain plus index."""
        domain = urlsplit(url).netloc.lower()
        domain = domain.removeprefix("www.")
        root = domain.split(".")[0]
        root = re.sub(r"[^a-zA-Z0-9]", "", root).title() or "Web"
        return f"[{root}{index}]"

    @staticmethod
    def _fallback_title(url: str) -> str:
        """Create a basic title from a URL."""
        parsed = urlsplit(url)
        path_name = parsed.path.rstrip("/").split("/")[-1]
        raw = path_name or parsed.netloc or "Untitled source"
        raw = re.sub(r"[-_]+", " ", raw)
        raw = re.sub(r"\.[a-zA-Z0-9]{2,5}$", "", raw)
        return raw.strip().title() or "Untitled source"

    def _format_failures(self) -> str:
        """Format failures for exceptions and logs."""
        if not self.last_failures:
            return "None"
        return "; ".join(
            f"{failure.url} -> {failure.reason}: {failure.detail}" for failure in self.last_failures
        )

    @staticmethod
    def _mock_output(job_id: str, topic: str) -> ResearchOutput:
        """Demo-only mock output."""
        source = Source(
            id=f"{job_id}-mock-source-1",
            job_id=job_id,
            title=f"Mock research source for {topic}",
            summary=f"Mock source summary about {topic}.",
            relevance_score=0.1,
            raw_text=f"Mock placeholder text for {topic}. Do not use in production.",
            citation_key="[Mock]",
        )
        return ResearchOutput(sources=[source])
