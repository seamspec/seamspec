"""Timestamps and durations as text."""

from __future__ import annotations

from datetime import UTC, datetime

FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def to_iso(seconds: float) -> str:
    return datetime.fromtimestamp(int(seconds), tz=UTC).strftime(FORMAT)


def from_iso(text: str) -> int:
    if not text.endswith("Z"):
        raise ValueError(f"not a timestamp: {text!r}")
    return int(datetime.strptime(text, FORMAT).replace(tzinfo=UTC).timestamp())


def duration_text(seconds: int) -> str:
    if seconds < 0:
        raise ValueError("a duration can't be below zero")
    if seconds < 60:
        return f"{seconds}s"
    hours, minutes = divmod(seconds // 60, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"
