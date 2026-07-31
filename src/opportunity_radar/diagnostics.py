from __future__ import annotations

import logging
import os
from urllib.parse import urlsplit, urlunsplit

DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"


def configure_logging() -> None:
    """Configure readable runtime diagnostics without logging request secrets."""
    requested_level = os.environ.get("OPPORTUNITY_RADAR_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, requested_level, logging.INFO)
    logging.basicConfig(
        level=level,
        format=DEFAULT_LOG_FORMAT,
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def safe_url(value: str) -> str:
    """Remove credentials, query parameters, and fragments before logging a URL."""
    parsed = urlsplit(value)
    hostname = parsed.hostname or ""
    if parsed.port is not None:
        hostname = f"{hostname}:{parsed.port}"
    return urlunsplit((parsed.scheme, hostname, parsed.path, "", ""))
