"""Structured logging configuration."""

import logging
import sys

import structlog

from app.config import Settings, get_settings


def configure_logging(settings: Settings | None = None) -> None:
    """Configure structlog JSON output for the application."""
    active_settings = settings or get_settings()
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, active_settings.log_level.upper(), logging.INFO),
        stream=sys.stdout,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, active_settings.log_level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structured logger."""
    return structlog.get_logger(name)
