"""SQLite-backed free-tier quota enforcement."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import QuotaCounterRecord, SessionLocal, init_db


class QuotaExceededError(RuntimeError):
    """Raised when a provider quota would be exceeded."""


@dataclass(frozen=True)
class QuotaLimits:
    """Provider quota limits."""

    nvidia_requests_per_minute: int
    nvidia_requests_per_day: int
    groq_requests_per_minute: int
    groq_requests_per_day: int
    groq_tokens_per_day: int


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class QuotaManager:
    """Track and enforce provider rolling and daily quota counters."""

    def __init__(
        self,
        limits: QuotaLimits | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize quota manager with configured limits."""
        settings = get_settings()
        self.limits = limits or QuotaLimits(
            nvidia_requests_per_minute=settings.nvidia_requests_per_minute_limit,
            nvidia_requests_per_day=settings.nvidia_daily_request_limit,
            groq_requests_per_minute=settings.groq_requests_per_minute_limit,
            groq_requests_per_day=settings.groq_daily_request_limit,
            groq_tokens_per_day=settings.groq_daily_token_limit,
        )
        self._clock = clock or _utc_now
        init_db()

    def check_and_increment(self, provider: str, *, tokens: int = 0) -> None:
        """Validate provider quota and increment counters atomically."""
        now = self._now()
        today = now.date().isoformat()
        with SessionLocal() as session:
            if provider == "nvidia":
                self._increment_rolling_window(
                    session,
                    provider=provider,
                    now=now,
                    request_limit=self.limits.nvidia_requests_per_minute,
                    label="NVIDIA NIM per-minute request quota",
                )
                self._increment(
                    session,
                    key=f"nvidia:{today}",
                    provider=provider,
                    bucket=today,
                    request_limit=self.limits.nvidia_requests_per_day,
                    label="NVIDIA NIM daily request quota",
                )
            elif provider == "groq":
                self._increment_rolling_window(
                    session,
                    provider=provider,
                    now=now,
                    request_limit=self.limits.groq_requests_per_minute,
                    label="Groq per-minute request quota",
                )
                self._increment(
                    session,
                    key=f"groq:{today}",
                    provider=provider,
                    bucket=today,
                    request_limit=self.limits.groq_requests_per_day,
                    token_limit=self.limits.groq_tokens_per_day,
                    tokens=tokens,
                    label="Groq daily quota",
                )
            session.commit()

    def status(self) -> dict[str, int]:
        """Return remaining free-tier quota counters."""
        now = self._now()
        today = now.date().isoformat()
        with SessionLocal() as session:
            nvidia_daily = session.scalar(
                select(QuotaCounterRecord).where(QuotaCounterRecord.key == f"nvidia:{today}")
            )
            groq_daily = session.scalar(
                select(QuotaCounterRecord).where(QuotaCounterRecord.key == f"groq:{today}")
            )
            nvidia_minute_requests = self._rolling_window_requests(session, "nvidia", now)
            nvidia_daily_requests = nvidia_daily.requests if nvidia_daily is not None else 0
            groq_minute_requests = self._rolling_window_requests(session, "groq", now)
            groq_daily_requests = groq_daily.requests if groq_daily is not None else 0
            groq_daily_tokens = groq_daily.tokens if groq_daily is not None else 0
        return {
            "nvidia_requests_per_minute_used": nvidia_minute_requests,
            "nvidia_requests_per_minute_remaining": self._remaining(
                self.limits.nvidia_requests_per_minute,
                nvidia_minute_requests,
            ),
            "nvidia_requests_used": nvidia_daily_requests,
            "nvidia_requests_remaining": self._remaining(
                self.limits.nvidia_requests_per_day,
                nvidia_daily_requests,
            ),
            "groq_requests_per_minute_used": groq_minute_requests,
            "groq_requests_per_minute_remaining": self._remaining(
                self.limits.groq_requests_per_minute,
                groq_minute_requests,
            ),
            "groq_requests_used": groq_daily_requests,
            "groq_requests_remaining": self._remaining(
                self.limits.groq_requests_per_day,
                groq_daily_requests,
            ),
            "groq_tokens_used": groq_daily_tokens,
            "groq_tokens_remaining": self._remaining(
                self.limits.groq_tokens_per_day,
                groq_daily_tokens,
            ),
        }

    def _now(self) -> datetime:
        current = self._clock()
        if current.tzinfo is None:
            return current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc)

    def _increment_rolling_window(
        self,
        session: Session,
        *,
        provider: str,
        now: datetime,
        request_limit: int,
        label: str,
    ) -> None:
        used = self._rolling_window_requests(session, provider, now)
        if request_limit > 0 and used + 1 > request_limit:
            raise QuotaExceededError(f"{label} exceeded")

        bucket = self._instant_bucket(now)
        self._increment(
            session,
            key=f"{provider}:rpm:{bucket}",
            provider=provider,
            bucket=bucket,
            request_limit=0,
            label=label,
        )

    @classmethod
    def _rolling_window_requests(cls, session: Session, provider: str, now: datetime) -> int:
        window_start = cls._instant_bucket(now - timedelta(seconds=60))
        window_end = cls._instant_bucket(now)
        used = session.scalar(
            select(func.coalesce(func.sum(QuotaCounterRecord.requests), 0))
            .where(QuotaCounterRecord.provider == provider)
            .where(QuotaCounterRecord.key.like(f"{provider}:rpm:%"))
            .where(QuotaCounterRecord.date > window_start)
            .where(QuotaCounterRecord.date <= window_end)
        )
        return int(used or 0)

    @staticmethod
    def _instant_bucket(value: datetime) -> str:
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _increment(
        session: Session,
        *,
        key: str,
        provider: str,
        bucket: str,
        request_limit: int,
        label: str,
        token_limit: int = 0,
        tokens: int = 0,
    ) -> None:
        record = session.scalar(select(QuotaCounterRecord).where(QuotaCounterRecord.key == key))
        if record is None:
            record = QuotaCounterRecord(key=key, provider=provider, date=bucket, requests=0, tokens=0)
            session.add(record)

        if request_limit > 0 and record.requests + 1 > request_limit:
            raise QuotaExceededError(f"{label} exceeded")
        if token_limit > 0 and record.tokens + tokens > token_limit:
            raise QuotaExceededError(f"{label} exceeded")

        record.requests += 1
        record.tokens += max(tokens, 0)

    @staticmethod
    def _remaining(limit: int, used: int) -> int:
        if limit <= 0:
            return -1
        return max(limit - used, 0)
