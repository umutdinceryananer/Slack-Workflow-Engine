"""Structlog configuration helpers for structured logging."""

from __future__ import annotations

import logging

import structlog

LOG_LEVEL = logging.INFO


def configure_logging() -> None:
    """Configure structlog to emit JSON-formatted logs."""

    timestamper = structlog.processors.TimeStamper(fmt="iso")

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            timestamper,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(level=LOG_LEVEL)
