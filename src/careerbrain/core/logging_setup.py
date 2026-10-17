from __future__ import annotations

import hashlib
import hmac
import json
import logging
import sys
from datetime import UTC, datetime
from typing import IO

HANDLER_NAME = "careerbrain-json"
EXTRA_FIELDS = ("event", "latency_ms", "tokens", "retries", "user_hash")


def hash_id(raw_id: str, key: bytes) -> str:
    return hmac.new(key, raw_id.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in EXTRA_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", stream: IO[str] | None = None) -> None:
    root = logging.getLogger()
    for existing in list(root.handlers):
        if existing.get_name() == HANDLER_NAME:
            root.removeHandler(existing)

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.set_name(HANDLER_NAME)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
