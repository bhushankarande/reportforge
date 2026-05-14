"""Research agent using URL-backed sources with mock fallback for MVP."""

import re

from app.logging_config import get_logger
from schemas.agent_outputs import ResearchOutput
from schemas.sources import Source
from orchestration.cost_tracking import CostTrackingModel
from tools.llm.model_router import ModelRouter
from tools.search.url_fetcher import fetch_url_text

logger = get_logger(__name__)

BOILERPLATE_FRAGMENTS = (
    "wp-block",
    "skip to",
    "share this article",
    "tools & services",
    "explore our latest",
    "external links",
    "cta button",
    "display: none",
    "request a quote",
    "products in interest",
    "want to hear more",
    "cookie",
    "privacy policy",
    "subscribe",
    "copyright",
    "linear inverted pendulum",
    "smart motion devices",
    "mobile autonomous robot",
    "acrobat 4-axis",
    "ball balancing table",
    "facebook",
    "linkedin",
    "x twitter",
)


class ResearchAgent:
    """Collect external sources with metadata and relevance scores."""

    def __init__(self, router: ModelRouter | None = None) -> None:
        """Initialize research agent."""
        self.router = router or ModelRouter()

    def research(self, job_id: str, topic: str, urls: list[str] | None = None) -> ResearchOutput:
        """Collect URL sources, or return deterministic mock sources when none are supplied."""
        tracked_model = CostTrackingModel(self.router.get_model())
        tracked_model(f"Summarize research context for {topic}")
        url_sources = self._sources_from_urls(job_id, topic, urls or [])
        if url_sources:
            logger.info("research_url_sources_collected", job_id=job_id, sources=len(url_sources))
            return ResearchOutput(sources=url_sources)
        source = Source(
            id=f"{job_id}-mock-source-1",
            job_id=job_id,
            title=f"Mock research source for {topic}",
            summary=f"Mock source summary about {topic}.",
            relevance_score=0.85,
            raw_text=f"{topic} has relevant market and technical evidence.",
            citation_key="[Mock2026]",
        )
        return ResearchOutput(sources=[source])

    def _sources_from_urls(self, job_id: str, topic: str, urls: list[str]) -> list[Source]:
        """Fetch user-provided URLs into source records."""
        sources: list[Source] = []
        for index, url in enumerate(urls, start=1):
            if not url.startswith(("http://", "https://")):
                logger.warning("research_url_skipped", job_id=job_id, url=url, reason="invalid_scheme")
                continue
            citation_key = f"[Web{index}]"
            try:
                title, text = fetch_url_text(url)
            except Exception as exc:
                logger.warning("research_url_fetch_failed", job_id=job_id, url=url, error=str(exc))
                continue
            excerpt = self._topic_excerpt(text, topic)
            if not excerpt:
                continue
            summary = excerpt[:900]
            sources.append(
                Source(
                    id=f"{job_id}-web-source-{index}",
                    job_id=job_id,
                    title=title,
                    url=url,
                    summary=summary,
                    relevance_score=max(0.2, 0.95 - (index - 1) * 0.08),
                    raw_text=f"{excerpt} {citation_key}",
                    citation_key=citation_key,
                )
            )
        if urls and not sources:
            logger.warning("research_all_url_fetches_failed", job_id=job_id, topic=topic)
        return sources

    @staticmethod
    def _topic_excerpt(text: str, topic: str, *, max_chars: int = 2_500) -> str:
        """Return a compact excerpt biased toward the requested topic."""
        cleaned = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
        cleaned = re.sub(r"\{[^{}]{0,500}\}", " ", cleaned)
        cleaned = re.sub(r"<svg.*", " ", cleaned, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        terms = {
            token
            for token in re.findall(r"[a-z0-9]+", topic.lower())
            if len(token) >= 5
        } | {"robot", "robots", "robotics", "language", "model", "models", "task", "planning", "llm"}
        sentences: list[str] = []
        seen: set[str] = set()
        for sentence in re.split(r"(?<=[.!?])\s+", cleaned):
            normalized = re.sub(r"\s+", " ", sentence).strip(" -•")
            key = normalized.lower()
            if key in seen or not ResearchAgent._is_useful_sentence(normalized):
                continue
            sentences.append(normalized)
            seen.add(key)
        ranked = sorted(
            sentences,
            key=lambda sentence: sum(1 for term in terms if term in sentence.lower()),
            reverse=True,
        )
        selected = [sentence for sentence in ranked if any(term in sentence.lower() for term in terms)][:8]
        excerpt = " ".join(selected) or cleaned[:max_chars]
        return excerpt[:max_chars].strip()

    @staticmethod
    def _is_useful_sentence(sentence: str) -> bool:
        """Return whether scraped text is useful evidence rather than page chrome."""
        if not 45 <= len(sentence) <= 520:
            return False
        lower = sentence.lower()
        if any(fragment in lower for fragment in BOILERPLATE_FRAGMENTS):
            return False
        if "keywords:" in lower or re.search(r"\bfigure\s+\d+\b", lower):
            return False
        words = re.findall(r"[A-Za-z][A-Za-z-]+", sentence)
        if len(words) < 8:
            return False
        alpha_ratio = sum(char.isalpha() or char.isspace() for char in sentence) / max(len(sentence), 1)
        if alpha_ratio < 0.65:
            return False
        uppercase_words = [word for word in words if len(word) > 3 and word.isupper()]
        return len(uppercase_words) <= max(2, len(words) // 5)
