"""Rule: a refused commit names each failing rule by id and title and shows the check that failed,
before any raw test output (ADR-20261013-4e9b)."""

from pathlib import Path

from typer.testing import CliRunner

from seamspec.cli import app
from seamspec.core import lifecycle
from seamspec.core.config import load_config
from seamspec.core.store import Store
from seamspec.installers import scaffold

TEST = "from src.queue import backoff_delay\n\n\ndef test_cap():\n    assert backoff_delay(100) <= 30\n"


def test_the_refusal_says_which_rule_and_which_check(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    (tmp_path / ".git").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src/queue.py").write_text("def backoff_delay(n):\n    return min(0.1 * 2 ** n, 30.0)\n")
    scaffold.init(tmp_path, auto_run=True, actor="Maya <maya@example.com>")
    store, cfg = Store(tmp_path), load_config(tmp_path)
    inv_id = lifecycle.propose_invariant(
        store, cfg, title="Retry delay is capped", assertion="Retry delay never exceeds 30 seconds.",
        scope_paths=["src/queue*"], runner="pytest", harness_code=TEST, origin_text="x",
    )["id"]  # fmt: skip
    lifecycle.approve(store, cfg, inv_id, via="chat")
    (tmp_path / "src/queue.py").write_text("def backoff_delay(n):\n    return 99.0\n")  # the regression
    monkeypatch.chdir(tmp_path)

    refused = CliRunner().invoke(app, ["verify", "--all", "--gate"])  # what the pre-commit hook runs

    assert refused.exit_code == 1
    named = f"{inv_id} · Retry delay is capped"
    check = "line 5: assert backoff_delay(100) <= 30"
    assert named in refused.output and check in refused.output and "assert 99.0 <= 30" in refused.output
    assert "commit blocked" in refused.output
    assert "short test summary" not in refused.output  # the runner's own output is not dumped on top
