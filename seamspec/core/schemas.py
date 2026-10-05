"""Packaged JSON Schemas and validation (SPEC §9.4).

Validation always uses the packaged copy; the `$id` URLs are identifiers, not runtime dependencies.
"""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_VERSION = "1"
NAMES = ("invariant", "dead_end", "config")


@cache
def load_schema(name: str) -> dict[str, Any]:
    if name not in NAMES:
        raise KeyError(f"unknown schema {name!r}; expected one of {NAMES}")
    text = files("seamspec.schemas").joinpath(f"v{SCHEMA_VERSION}", f"{name}.json").read_text("utf-8")
    return json.loads(text)


@cache
def _validator(name: str) -> Draft202012Validator:
    schema = load_schema(name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validation_errors(name: str, data: Any) -> list[str]:
    """Human-readable schema errors for `data`; empty when it is valid."""
    errors = sorted(_validator(name).iter_errors(data), key=lambda e: list(e.absolute_path))
    out = []
    for err in errors:
        where = "/".join(str(p) for p in err.absolute_path) or "(root)"
        out.append(f"{where}: {err.message}")
    return out
