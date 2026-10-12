"""Record ids such as `ord-000042`."""

from __future__ import annotations

LARGEST = 999_999


def make_id(prefix: str, number: int) -> str:
    if not prefix.isalpha():
        raise ValueError(f"bad prefix: {prefix!r}")
    if number < 0 or number > LARGEST:
        raise ValueError(f"bad number: {number}")
    return f"{prefix.lower()}-{number:06d}"


def parse_id(text: str) -> tuple[str, int]:
    prefix, dash, digits = text.partition("-")
    if not dash or not prefix.isalpha() or prefix != prefix.lower() or len(digits) != 6 or not digits.isdigit():
        raise ValueError(f"bad id: {text!r}")
    return prefix, int(digits)
