"""Rule: red-green never reports a plain YES when the test fails on the last commit only because
the code it tests isn't there yet. It says so, since such a failure proves nothing about the test
(ADR-20261013-a5d3)."""

import os
import subprocess
from pathlib import Path

from seamspec.core import lifecycle, redgreen
from seamspec.core.config import load_config
from seamspec.core.store import Store
from seamspec.installers import scaffold

OLD = "def backoff_delay(n):\n    return min(0.1 * 2 ** n, 30.0)\n"
WHO = {"GIT_AUTHOR_NAME": "Maya", "GIT_AUTHOR_EMAIL": "maya@example.com",
       "GIT_COMMITTER_NAME": "Maya", "GIT_COMMITTER_EMAIL": "maya@example.com"}  # fmt: skip


def project(tmp_path: Path) -> Store:
    """A committed project; whatever a test changes afterwards is 'your change'."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    (tmp_path / "src").mkdir()
    (tmp_path / "src/queue.py").write_text(OLD)
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "start"]):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, env={**os.environ, **WHO})
    scaffold.init(tmp_path, auto_run=True, actor="Maya <maya@example.com>")
    return Store(tmp_path)


def check(store: Store, code: str) -> redgreen.RedGreen:
    cfg = load_config(store.root)
    inv_id = lifecycle.propose_invariant(store, cfg, title="A new rule", assertion="The new behavior holds.",
                                         scope_paths=["src/**"], runner="pytest", harness_code=code,
                                         origin_text="x")["id"]  # fmt: skip
    return redgreen.check(store, cfg, store.get(inv_id))


def test_a_test_of_code_that_did_not_exist_is_not_a_plain_yes(tmp_path: Path) -> None:
    store = project(tmp_path)
    (tmp_path / "src/queue.py").write_text(OLD + "\n\ndef jitter(x):\n    return x / 2\n")
    result = check(store, "from src.queue import jitter\n\n\ndef test_jitter():\n    assert jitter(10) == 5\n")
    assert result.verdict == "yes" and result.new_code
    assert "ONLY BECAUSE THE CODE IS NEW" in result.line() and result.hint()


def test_changed_behavior_is_a_plain_yes_that_quotes_the_failure(tmp_path: Path) -> None:
    store = project(tmp_path)
    (tmp_path / "src/queue.py").write_text(OLD.replace("30.0", "60.0"))
    result = check(store, "from src.queue import backoff_delay\n\n\ndef test_cap():\n    assert backoff_delay(100) == 60\n")
    assert result.verdict == "yes" and not result.new_code and result.hint() is None
    assert "on HEAD: assert 30.0 == 60" in result.line()
