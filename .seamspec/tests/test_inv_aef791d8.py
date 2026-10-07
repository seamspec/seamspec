"""Locked rule: a scripted `seamspec init --accept-auto-run` never trusts a clone's committed runner
commands; trusting them needs a human at a terminal (SPEC §12.4.5, ADR-20261005-9b8f)."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from seamspec.cli import app
from seamspec.core import trust
from seamspec.core.config import load_config
from seamspec.core.store import Store
from seamspec.installers import scaffold


def test_scripted_init_never_trusts_a_clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    scaffold.init(repo, auto_run=True, actor="Maya")
    (repo / ".seamspec/.local/trust.json").unlink()  # what a fresh clone looks like on a new machine
    result = CliRunner().invoke(
        app, ["init", "--path", str(repo), "--no-claude-md", "--no-plugin", "--accept-auto-run"]
    )
    assert result.exit_code == 0, result.output
    assert not trust.state(Store(repo), load_config(repo)).trusted
