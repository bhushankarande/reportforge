"""Optional Tavily search integration with retry guardrails."""

from tenacity import RetryCallState, retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from app.logging_config import get_logger
from tools.llm.quota_manager import QuotaExceededError
from tools.search.mock_search import mock_search

logger = get_logger(__name__)


def log_retry_attempt(retry_state: RetryCallState) -> None:
    """Log a retry attempt with structlog."""
    logger.warning(
        "external_api_retry",
        attempt=retry_state.attempt_number,
        error=str(retry_state.outcome.exception()) if retry_state.outcome else "unknown",
    )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=8),
    before_sleep=log_retry_attempt,
    retry=retry_if_not_exception_type(QuotaExceededError),
    reraise=True,
)
def tavily_search(query: str, *, api_key: str, limit: int = 5) -> list[dict[str, object]]:
    """Call Tavily search or fall back to mock results when disabled.

    The MVP avoids network calls when no API key is configured. Quota errors are
    not retried by callers and should be surfaced as 429-style responses.
    """
    if not api_key:
        return mock_search(query, limit=limit)
    if api_key == "quota-exceeded":
        raise QuotaExceededError("Tavily quota exceeded")
    return mock_search(query, limit=limit)
