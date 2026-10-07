"""Locked rule: `seamspec init` never changes Claude Code settings without a yes: with no terminal
and no --plugin flag it doesn't even call `claude` (ADR-20261005-428a)."""

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from seamspec.cli import app


def test_init_without_terminal_or_flag_never_calls_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "claude-calls.log"
    fake = bindir / "claude"
    fake.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\n')
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))
    repo = tmp_path / "repo"
    repo.mkdir()
    result = CliRunner().invoke(app, ["init", "--path", str(repo), "--mode", "advisory", "--no-claude-md"])
    assert result.exit_code == 0, result.output
    assert not log.exists()
    assert not (repo / ".claude").exists()
