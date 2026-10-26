"""Log lines for the log collector."""

from __future__ import annotations

import json

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
MASKED = ("password", "token", "secret")


def line(level: str, message: str, /, **fields: object) -> str:
    level = level.upper()
    if level not in LEVELS:
        raise ValueError(f"unknown level {level!r}")
    record = {k: ("***" if k.lower() in MASKED else v) for k, v in fields.items() if k not in ("level", "message")}
    record.update(level=level, message=str(message))
    return json.dumps(record, sort_keys=True, ensure_ascii=True)
