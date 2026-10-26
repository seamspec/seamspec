"""SeamSpec's record of each time it sent the agent back (ADR-20261018-6e1a)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from seamspec.adapters import claude
from seamspec.cli import app
from seamspec.core import catches
from seamspec.core.config import load_config
from seamspec.core.store import Store

from .conftest import git
from .test_claude_adapter import BROKEN_CODE, lock

runner = CliRunner()


@pytest.fixture
def human(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")


def test_a_blocked_finish_and_a_refused_commit_are_recorded(git_repo: Path, human: None, monkeypatch) -> None:
    inv_id = lock(git_repo)
    store, cfg = Store(git_repo), load_config(git_repo)
    assert catches.counts(store) == {"stop": 0, "commit": 0}
    assert claude.stop({"session_id": "s1", "stop_hook_active": False}, store, cfg) is None  # green: nothing caught
    (git_repo / "src/queue.py").write_text(BROKEN_CODE)
    out = claude.stop({"session_id": "s1", "stop_hook_active": False}, store, cfg)
    assert out["decision"] == "block"
    assert catches.load(store)[-1]["kind"] == "stop" and catches.load(store)[-1]["ids"] == [inv_id]

    monkeypatch.chdir(git_repo)
    git(git_repo, "add", "src/queue.py")  # the commit check tests what is staged
    refused = runner.invoke(app, ["verify", "--all", "--gate"])
    assert refused.exit_code == 1
    assert catches.counts(store) == {"stop": 1, "commit": 1}
    status = runner.invoke(app, ["status"])
    assert "caught      1 at the end of a task, 1 at a commit" in status.output
    assert json.loads(runner.invoke(app, ["status", "--json"]).output)["catches"] == {"stop": 1, "commit": 1}


def test_a_broken_record_line_is_skipped(tmp_path: Path) -> None:
    (tmp_path / ".seamspec").mkdir()
    store = Store(tmp_path)
    (store.local / catches.CATCHES).write_text('not json\n{"kind": "other"}\n{"kind": "stop", "ids": []}\n')
    assert catches.counts(store) == {"stop": 1, "commit": 0}
