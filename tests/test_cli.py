from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from seamspec import __version__
from seamspec.cli import app
from seamspec.core.models import InvStatus
from seamspec.core.store import Store

from .conftest import make_dead_end, make_invariant

runner = CliRunner()


@pytest.fixture
def in_repo(repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(repo)
    return repo


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0 and __version__ in result.output


def test_init_command(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("")
    result = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "created   .seamspec/config.toml" in result.output
    assert "Runners: pytest" in result.output
    assert "not a git repository" in result.output


def test_init_reports_unsupported_language(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module x")
    result = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert "go detected; support arrives in v0.2" in result.output


def test_init_says_which_lines_it_kept(tmp_path: Path) -> None:
    """Dogfooding #8: a line written inside SeamSpec's CLAUDE.md block is kept, and init shows it."""
    runner.invoke(app, ["init", "--path", str(tmp_path)])
    path = tmp_path / "CLAUDE.md"
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], "Commit straight to main.", *lines[1:]]) + "\n")
    result = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "1 line inside SeamSpec's block was not SeamSpec's. Kept, and moved above the block:" in result.output
    assert "    | Commit straight to main." in result.output
    assert path.read_text().startswith("Commit straight to main.\n\n<!-- seamspec:begin")
    again = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert "unchanged CLAUDE.md" in again.output and "Kept" not in again.output


def test_init_broken_claude_md(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("<!-- seamspec:begin -->\n")
    result = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert result.exit_code == 1 and "markers" in result.output


def test_commands_outside_a_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    for args in (["status"], ["context", "x.py"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 1 and "seamspec init" in result.output


def test_status(in_repo: Path) -> None:
    store = Store(in_repo)
    store.create(make_invariant("inv_00000001", InvStatus.LOCKED))
    store.create(make_invariant("inv_00000002"))
    store.create(make_dead_end())
    data = json.loads(runner.invoke(app, ["status", "--json"]).output)
    assert data["invariants"] == {"PROPOSED": 1, "LOCKED": 1, "SUPERSEDED": 0, "REJECTED": 0}
    assert data["dead_ends"] == {"ACTIVE": 1, "RETIRED": 0}
    assert data["awaiting_review"] == 1 and data["last_verify"] is None
    text = runner.invoke(app, ["status"]).output
    assert "1 awaiting review: run `seamspec review`." in text


def test_status_reports_bad_record(in_repo: Path) -> None:
    (in_repo / ".seamspec/invariants/inv_deadbeef.json").write_text("{}")
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 1 and "inv_deadbeef.json" in result.output


def test_status_reports_bad_config(in_repo: Path) -> None:
    (in_repo / ".seamspec/config.toml").write_text("mode = 'loose'\n")
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 1 and "config.toml" in result.output


def test_context(in_repo: Path) -> None:
    Store(in_repo).create(make_invariant(status=InvStatus.LOCKED))
    Store(in_repo).create(make_dead_end())
    text = runner.invoke(app, ["context", "src/queue/redis.py"]).output
    assert text.startswith("SeamSpec: src/queue/redis.py is governed by:")
    assert "[LOCKED] inv_1a2b3c4d" in text and "Previously tried and failed" in text

    data = json.loads(runner.invoke(app, ["context", "--json", "src/queue/redis.py"]).output)
    assert data["files"] == ["src/queue/redis.py"] and len(data["locked"]) == 1

    none = runner.invoke(app, ["context", "README.md"]).output
    assert "no invariants or dead ends apply to README.md" in none


def test_context_from_subdirectory(in_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    Store(in_repo).create(make_invariant(status=InvStatus.LOCKED))
    sub = in_repo / "src/queue"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    text = runner.invoke(app, ["context", "redis.py"]).output
    assert "src/queue/redis.py is governed by" in text
