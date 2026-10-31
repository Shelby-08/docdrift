import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any, TextIO

SENSITIVE_PATTERN = re.compile(
    r"(key|secret|token|authorization|password|signature)", re.IGNORECASE
)

# Attributes every LogRecord has; anything else was passed through `extra=`.
_STANDARD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


def redact(value: Any) -> Any:
    """Return a copy of value where every sensitive-looking key is replaced by [REDACTED]."""
    if isinstance(value, dict):
        return {
            k: "[REDACTED]" if SENSITIVE_PATTERN.search(str(k)) else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    """Format each record as one JSON line, redacting sensitive keys."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "time": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS:
                log_data[key] = value
        return json.dumps(redact(log_data), default=str)


def create_logger(level: str, stream: TextIO | None = None) -> logging.Logger:
    """Create a JSON-line logger."""
    logger = logging.getLogger("docsentry")
    logger.setLevel(level.upper())
    logger.propagate = False  # Don't propagate to root
    logger.handlers.clear()  # Calling this twice must not print every line twice

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setLevel(level.upper())
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    return logger
