"""Settings read from environment variables."""

from __future__ import annotations

PREFIX = "APP_"
DEFAULTS = {"batch_size": 50, "max_items": 500, "verbose": False, "region": "eu"}


def _convert(key: str, raw: str) -> object:
    default = DEFAULTS[key]
    if isinstance(default, bool):
        if raw not in ("true", "false"):
            raise ValueError(f"{key}: expected true or false, got {raw!r}")
        return raw == "true"
    if isinstance(default, int):
        value = int(raw)
        if value <= 0:
            raise ValueError(f"{key}: must be positive, got {value}")
        return value
    if not raw:
        raise ValueError(f"{key}: empty")
    return raw


def load(env: dict[str, str]) -> dict[str, object]:
    settings: dict[str, object] = dict(DEFAULTS)
    for name, raw in env.items():
        if not name.startswith(PREFIX):
            continue
        key = name[len(PREFIX) :].lower()
        if key not in DEFAULTS:
            raise KeyError(f"unknown setting {name}")
        settings[key] = _convert(key, raw.strip())
    return settings
