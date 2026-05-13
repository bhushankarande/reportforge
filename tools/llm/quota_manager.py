"""SQLite-backed free-tier quota enforcement."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select

from app.config import get_settings
from app.database import QuotaCounterRecord, SessionLocal, init_db


class QuotaExceededError(RuntimeError):
    """Raised when a provider quota would be exceeded."""


@dataclass(frozen=True)
class QuotaLimits:
    """Provider quota limits."""

    gemini_requests_per_day: int
    groq_tokens_per_day: int


class QuotaManager:
    """Track and enforce provider daily quota counters."""

    def __init__(self, limits: QuotaLimits | None = None) -> None:
        """Initialize quota manager with configured limits."""
        settings = get_settings()
        self.limits = limits or QuotaLimits(
            gemini_requests_per_day=settings.gemini_daily_request_limit,
            groq_tokens_per_day=settings.groq_daily_token_limit,
        )
        init_db()

    def check_and_increment(self, provider: str, *, tokens: int = 0) -> None:
        """Validate provider quota and increment counters atomically."""
        today = date.today().isoformat()
        key = f"{provider}:{today}"
        with SessionLocal() as session:
            record = session.scalar(select(QuotaCounterRecord).where(QuotaCounterRecord.key == key))
            if record is None:
                record = QuotaCounterRecord(key=key, provider=provider, date=today, requests=0, tokens=0)
                session.add(record)

            if provider == "gemini" and record.requests + 1 > self.limits.gemini_requests_per_day:
                raise QuotaExceededError("Gemini daily request quota exceeded")
            if provider == "groq" and record.tokens + tokens > self.limits.groq_tokens_per_day:
                raise QuotaExceededError("Groq daily token quota exceeded")

            record.requests += 1
            record.tokens += max(tokens, 0)
            session.commit()
