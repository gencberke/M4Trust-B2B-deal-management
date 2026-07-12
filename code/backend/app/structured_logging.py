"""Allowlisted JSON logging for request/audit operational context."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

_STRING_FIELDS = (
    "event",
    "request_id",
    "actor_type",
    "actor_user_id",
    "acting_entity_id",
    "action",
    "outcome",
    "reason_code",
)
_NUMBER_FIELDS = ("status_code", "duration_ms", "item_count")
_SAFE_STRING = re.compile(r"^[A-Za-z0-9._:/-]{1,160}$")
_FORBIDDEN_VALUE_MARKERS = (
    "password",
    "token",
    "secret",
    "authorization",
    "checkkey",
    "card",
    "pan",
    "cvc",
    "cvv",
    "iban",
)


class AllowlistJSONFormatter(logging.Formatter):
    """Never serializes arbitrary message/args/exception payloads."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": "application_event",
        }
        for field in _STRING_FIELDS:
            value = getattr(record, field, None)
            if (
                isinstance(value, str)
                and _SAFE_STRING.fullmatch(value)
                and not any(marker in value.lower() for marker in _FORBIDDEN_VALUE_MARKERS)
            ):
                payload[field] = value
        for field in _NUMBER_FIELDS:
            value = getattr(record, field, None)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                payload[field] = value
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def configure_structured_logging() -> None:
    logger = logging.getLogger("backend")
    if any(getattr(handler, "_m4trust_structured", False) for handler in logger.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(AllowlistJSONFormatter())
    handler._m4trust_structured = True  # type: ignore[attr-defined]
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
