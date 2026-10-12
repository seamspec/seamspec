"""Pages of a list, for the admin screens."""

from __future__ import annotations

from collections.abc import Sequence

LARGEST_PAGE = 100


def page(items: Sequence[object], number: int = 1, size: int = 20) -> dict[str, object]:
    if number < 1 or size < 1:
        raise ValueError("page number and size start at 1")
    size = min(size, LARGEST_PAGE)
    start = (number - 1) * size
    return {"items": list(items[start : start + size]), "page": number, "size": size, "total": len(items)}
