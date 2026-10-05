from __future__ import annotations

from pathlib import Path

import pytest

from seamspec.core.config import load_config
from seamspec.core.hashing import normalize_text, sha256_text
from seamspec.core.scope import effective_protected_paths, matches


@pytest.mark.parametrize(
    "patterns,path,expected",
    [
        (["src/queue/**"], "src/queue/redis.py", True),
        (["src/queue/**"], "src/queue/a/b/c.py", True),
        (["src/queue/**"], "src/queues.py", False),
        (["src/queue/**"], "lib/src/queue/x.py", False),
        (["*.py"], "deep/nested/x.py", True),
        (["/top.py"], "top.py", True),
        (["/top.py"], "sub/top.py", False),
        (["src/**", "!src/generated/**"], "src/generated/x.py", False),
        (["src/**", "!src/generated/**"], "src/real.py", True),
    ],
)
def test_matches(patterns: list[str], path: str, expected: bool) -> None:
    assert matches(patterns, path) is expected


def test_effective_protected_paths(repo: Path) -> None:
    globs = effective_protected_paths(load_config(repo))
    assert ".seamspec/**" in globs
    assert ".seamspec/tests/test_inv_*.py" in globs
    assert ".seamspec/pytest.ini" in globs
    assert matches(globs, ".seamspec/invariants/inv_1a2b3c4d.json")
    assert not matches(globs, "src/app.py")


def test_assertion_hash_ignores_case_and_whitespace() -> None:
    assert normalize_text("  Retry\n delay   NEVER exceeds 30s ") == "retry delay never exceeds 30s"
    assert sha256_text("Retry delay never exceeds 30s") == sha256_text("retry  delay\nnever exceeds 30s")
    assert sha256_text("Retry delay never exceeds 30s") != sha256_text("Retry delay never exceeds 60s")
