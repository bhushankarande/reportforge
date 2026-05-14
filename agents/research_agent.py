"""Research agent using URL-backed sources with mock fallback for MVP."""

import re

from app.logging_config import get_logger
from schemas.agent_outputs import ResearchOutput
from schemas.sources import Source
from orchestration.cost_tracking import CostTrackingModel
from tools.llm.model_router import ModelRouter
from tools.search.url_fetcher import fetch_url_text

logger = get_logger(__name__)


class ResearchAgent:
    """Collect external sources with metadata and relevance scores."""

    def __init__(self, router: ModelRouter | None = None) -> None:
        """Initialize research agent."""
        self.router = router or ModelRouter()

    def research(self, job_id: str, topic: str, urls: list[str] | None = None) -> ResearchOutput:
        """Collect URL sources, or return deterministic mock sources when none are supplied."""
        tracked_model = CostTrackingModel(self.router.get_model("gemini"))
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
            summary = excerpt[:700]
            sources.append(
                Source(
                    id=f"{job_id}-web-source-{index}",
                    job_id=job_id,
                    title=title,
                    url=url,
                    summary=summary,
                    relevance_score=max(0.2, 0.95 - (index - 1) * 0.08),
                    raw_text=f"{summary} {citation_key}",
                    citation_key=citation_key,
                )
            )
        if urls and not sources:
            logger.warning("research_all_url_fetches_failed", job_id=job_id, topic=topic)
        return sources

    @staticmethod
    def _topic_excerpt(text: str, topic: str, *, max_chars: int = 900) -> str:
        """Return a compact excerpt biased toward the requested topic."""
        cleaned = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
        cleaned = re.sub(r"\{[^{}]{0,500}\}", " ", cleaned)
        cleaned = re.sub(r"<svg.*", " ", cleaned, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        boilerplate = (
            "wp-block",
            "skip to",
            "share this article",
            "tools & services",
            "explore our latest",
            "external links",
            "cta button",
            "display: none",
        )
        terms = {
            token
            for token in re.findall(r"[a-z0-9]+", topic.lower())
            if len(token) >= 5
        } | {"robot", "robots", "robotics", "language", "model", "models", "task", "planning", "llm"}
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", cleaned)
            if 40 <= len(sentence.strip()) <= 500
            and not any(fragment in sentence.lower() for fragment in boilerplate)
        ]
        ranked = sorted(
            sentences,
            key=lambda sentence: sum(1 for term in terms if term in sentence.lower()),
            reverse=True,
        )
        selected = [sentence for sentence in ranked if any(term in sentence.lower() for term in terms)][:3]
        excerpt = " ".join(selected) or cleaned[:max_chars]
        return excerpt[:max_chars].strip()
