"""SHA-256 helpers for integrity checks (SPEC §19.5)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def sha256_text(text: str) -> str:
    """Hash of whitespace-normalized, lowercased text: reflowing an assertion doesn't change it."""
    return sha256_bytes(normalize_text(text).encode("utf-8"))
