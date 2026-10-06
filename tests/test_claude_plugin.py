"""`seamspec init` installs the Claude Code plugin through `claude plugin ...` (SPEC §16.1)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from seamspec.cli import app
from seamspec.installers import claude_plugin

runner = CliRunner()
CHECKOUT = Path(__file__).resolve().parents[1]

FAKE = """#!/bin/sh
echo "$*" >> "$FAKE_CLAUDE_LOG"
case "$*" in
  "plugin list --json") cat "$FAKE_CLAUDE_LIST" 2>/dev/null || echo "[]" ;;
  *"$FAKE_CLAUDE_FAIL"*) echo '{"outcome":"error","message":"boom"}'; exit 1 ;;
  *) mkdir -p .claude && echo '{}' > .claude/settings.local.json; echo '{"outcome":"ok","message":"done"}' ;;
esac
"""


@pytest.fixture
def fake_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A `claude` stand-in first on PATH; returns its call log."""
    bindir = tmp_path / "fakebin"
    bindir.mkdir()
    (bindir / "claude").write_text(FAKE)
    (bindir / "claude").chmod(0o755)
    log = tmp_path / "claude.log"
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("FAKE_CLAUDE_LIST", str(tmp_path / "list.json"))
    monkeypatch.setenv("FAKE_CLAUDE_FAIL", "nothing-fails")
    return log


def calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    return root


def test_marketplace_is_the_checkout() -> None:
    assert claude_plugin.marketplace_source() == CHECKOUT
    market = json.loads((CHECKOUT / ".claude-plugin/marketplace.json").read_text())
    assert market["name"] == "seamspec"  # PLUGIN_ID is <plugin>@<marketplace>
    assert market["plugins"] == [{**market["plugins"][0], "name": "seamspec", "source": "./seamspec-plugin"}]


def test_install_runs_claudes_own_cli_at_local_scope(fake_claude: Path, project: Path) -> None:
    result = claude_plugin.install(project)
    assert result.status == "installed" and result.gitignore == "created"
    assert calls(fake_claude) == [
        "plugin list --json",
        f"plugin marketplace add {CHECKOUT} --scope local --json",
        "plugin install seamspec@seamspec --scope local --json",
    ]
    assert ".claude/settings.local.json" in (project / ".gitignore").read_text()  # holds this machine's path


@pytest.mark.parametrize("scope", ["local", "user"])
def test_already_enabled_is_left_alone(fake_claude: Path, project: Path, tmp_path: Path, scope: str) -> None:
    entry = {"id": "seamspec@seamspec", "scope": scope, "enabled": True}
    if scope == "local":
        entry["projectPath"] = str(project)
    (tmp_path / "list.json").write_text(json.dumps([entry]))
    assert claude_plugin.install(project).status == "unchanged"
    assert calls(fake_claude) == ["plugin list --json"]


def test_enabled_for_another_project_does_not_count(fake_claude: Path, project: Path, tmp_path: Path) -> None:
    other = {"id": "seamspec@seamspec", "scope": "local", "enabled": True, "projectPath": str(tmp_path)}
    (tmp_path / "list.json").write_text(json.dumps([other]))
    assert claude_plugin.install(project).status == "installed"


def test_a_failing_step_is_reported(fake_claude: Path, project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_FAIL", "plugin install")
    result = claude_plugin.install(project)
    assert result.status == "failed" and "claude plugin install" in result.message and "boom" in result.message
    # `marketplace add` already wrote this machine's path into settings.local.json: still ignored
    assert result.gitignore == "created" and ".claude/settings.local.json" in (project / ".gitignore").read_text()


def test_a_manual_install_is_ignored_too(fake_claude: Path, project: Path, tmp_path: Path) -> None:
    """Installed by hand earlier: init reports unchanged and still keeps the local settings out of git."""
    (tmp_path / "list.json").write_text(
        json.dumps([{"id": "seamspec@seamspec", "scope": "local", "enabled": True, "projectPath": str(project)}])
    )
    (project / ".claude").mkdir()
    (project / ".claude/settings.local.json").write_text("{}")
    result = claude_plugin.install(project)
    assert result.status == "unchanged" and result.gitignore == "created"
    assert ".claude/settings.local.json" in (project / ".gitignore").read_text()


def test_no_claude_cli_is_skipped(project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    result = claude_plugin.install(project)
    assert result.status == "skipped" and "not found" in result.message


def test_no_checkout_is_skipped(fake_claude: Path, project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(claude_plugin, "marketplace_source", lambda: None)
    result = claude_plugin.install(project)
    assert result.status == "skipped" and "ships with the release" in result.message
    assert calls(fake_claude) == []


# --- through `seamspec init` -------------------------------------------------------------------


def init(project: Path, *args: str, input: str = "") -> str:
    result = runner.invoke(app, ["init", "--path", str(project), "--mode", "advisory", "--no-claude-md", *args], input)
    assert result.exit_code == 0, result.output
    return result.output


def test_no_terminal_never_changes_claude_settings(fake_claude: Path, project: Path) -> None:
    out = init(project)
    assert "seamspec init --plugin" in out
    assert calls(fake_claude) == []


def test_flag_installs_without_asking(fake_claude: Path, project: Path) -> None:
    out = init(project, "--plugin")
    assert "Claude Code plugin: installed" in out and "/reload-plugins" in out
    assert len(calls(fake_claude)) == 3


def test_no_plugin_flag_runs_nothing(fake_claude: Path, project: Path) -> None:
    init(project, "--no-plugin")
    assert calls(fake_claude) == []


@pytest.mark.parametrize("answer", ["y", "n"])
def test_terminal_shows_the_commands_then_asks(
    fake_claude: Path, project: Path, monkeypatch: pytest.MonkeyPatch, answer: str
) -> None:
    monkeypatch.setattr("seamspec.cli._interactive", lambda: True)
    out = init(project, input=f"{answer}\n")
    assert f"claude plugin marketplace add {CHECKOUT} --scope local" in out
    assert "claude plugin install seamspec@seamspec --scope local" in out
    assert "just you, just this repository" in out
    assert ("Claude Code plugin: installed" in out) is (answer == "y")
    assert len(calls(fake_claude)) == (3 if answer == "y" else 1)


# --- the real Claude Code CLI, in a throwaway CLAUDE_CONFIG_DIR (conftest) -------------------------


@pytest.mark.skipif(shutil.which("claude") is None, reason="Claude Code CLI not installed")
def test_real_claude_cli_enables_it_for_this_repository_only(project: Path, tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    first = claude_plugin.install(project)
    assert first.status == "installed", first.message
    settings = json.loads((project / ".claude/settings.local.json").read_text())
    assert settings["enabledPlugins"] == {"seamspec@seamspec": True}
    assert claude_plugin.install(project).status == "unchanged"
    other = tmp_path / "other"
    other.mkdir()
    assert not claude_plugin.enabled_here(other)
