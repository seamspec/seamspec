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
    monkeypatch.delenv(claude_plugin.SOURCE_ENV, raising=False)
    return log


def calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    return root


@pytest.fixture
def released_build(monkeypatch: pytest.MonkeyPatch) -> str:
    """SeamSpec 0.1.0 installed from PyPI: no checkout to point at."""
    monkeypatch.setattr(claude_plugin, "checkout", lambda: None)
    monkeypatch.setattr(claude_plugin, "released", lambda: True)
    monkeypatch.setattr(claude_plugin, "__version__", "0.1.0")
    return "https://github.com/seamspec/seamspec.git#v0.1.0"


def test_marketplace_is_the_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(claude_plugin.SOURCE_ENV, raising=False)
    assert claude_plugin.marketplace_source() == str(CHECKOUT)
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


def test_an_unreleased_build_without_a_checkout_is_skipped(
    fake_claude: Path, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(claude_plugin, "checkout", lambda: None)
    monkeypatch.setattr(claude_plugin, "released", lambda: False)
    assert claude_plugin.marketplace_source() is None  # no tag to pin the plugin to
    result = claude_plugin.install(project)
    assert result.status == "skipped" and "unreleased build" in result.message and "--editable" in result.message
    assert calls(fake_claude) == []


# --- a released SeamSpec: the plugin from GitHub, pinned to the installed version (ADR-20261023-7d41) ---


def test_a_release_pins_the_plugin_to_its_own_tag(fake_claude: Path, released_build: str) -> None:
    assert claude_plugin.marketplace_source() == released_build
    assert claude_plugin.release_source("0.2.1") == "https://github.com/seamspec/seamspec.git#v0.2.1"


def test_the_environment_variable_overrides_the_source(fake_claude: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(claude_plugin.SOURCE_ENV, " seamspec/seamspec#main ")
    assert claude_plugin.marketplace_source() == "seamspec/seamspec#main"


@pytest.mark.parametrize(
    ("source", "ok"),
    [
        ("https://github.com/seamspec/seamspec.git#v0.1.0", True),
        ("seamspec/seamspec", True),
        ("seamspec/seamspec#v0.1.0", True),
        (str(CHECKOUT), False),
        ("./seamspec-plugin", False),
        ("tests/fixtures", False),  # looks like owner/repo, but it's a folder here
    ],
)
def test_only_a_published_source_can_be_shared(source: str, ok: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(CHECKOUT)
    assert claude_plugin.shareable(source) is ok


def test_project_scope_puts_the_published_plugin_in_the_committed_settings(
    fake_claude: Path, project: Path, released_build: str
) -> None:
    result = claude_plugin.install(project, "project")
    assert result.status == "installed" and ".claude/settings.json (commit it)" in result.message
    assert calls(fake_claude) == [
        "plugin list --json",
        f"plugin marketplace add {released_build} --scope project --json",
        "plugin install seamspec@seamspec --scope project --json",
    ]


@pytest.mark.parametrize("scope", ["local", "user"])
def test_enabled_for_you_alone_still_installs_for_the_team(
    fake_claude: Path, project: Path, tmp_path: Path, released_build: str, scope: str
) -> None:
    """`--plugin-scope project` reported unchanged when only this user had the plugin on (#97)."""
    entry = {"id": "seamspec@seamspec", "scope": scope, "enabled": True, "projectPath": str(project)}
    (tmp_path / "list.json").write_text(json.dumps([entry]))
    result = claude_plugin.install(project, "project")
    assert result.status == "installed" and "--scope project" in calls(fake_claude)[-1]


def test_project_scope_already_committed_is_left_alone(
    fake_claude: Path, project: Path, tmp_path: Path, released_build: str
) -> None:
    entry = {"id": "seamspec@seamspec", "scope": "project", "enabled": True, "projectPath": str(project)}
    (tmp_path / "list.json").write_text(json.dumps([entry]))
    result = claude_plugin.install(project, "project")
    assert result.status == "unchanged" and "for everyone in this repository" in result.message
    assert calls(fake_claude) == ["plugin list --json"]


def test_project_scope_never_shares_a_path_on_this_machine(fake_claude: Path, project: Path) -> None:
    result = claude_plugin.install(project, "project")
    assert result.status == "skipped" and "--plugin-scope local" in result.message
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


def test_plugin_scope_flag_installs_for_the_team(fake_claude: Path, project: Path, released_build: str) -> None:
    out = init(project, "--plugin", "--plugin-scope", "project")
    assert "enabled for everyone" in out and "Commit .claude/settings.json" in out
    assert f"plugin marketplace add {released_build} --scope project --json" in calls(fake_claude)


def test_a_wrong_plugin_scope_changes_nothing(fake_claude: Path, project: Path) -> None:
    result = runner.invoke(app, ["init", "--path", str(project), "--plugin", "--plugin-scope", "team"])
    assert result.exit_code != 0 and "local or project" in result.output
    assert not (project / ".seamspec").exists() and calls(fake_claude) == []


@pytest.mark.parametrize(("team", "scope"), [("y", "project"), ("n", "local"), ("", "local")])
def test_terminal_asks_whether_the_team_gets_it_too(
    fake_claude: Path, project: Path, released_build: str, monkeypatch: pytest.MonkeyPatch, team: str, scope: str
) -> None:
    monkeypatch.setattr("seamspec.cli._interactive", lambda: True)
    out = init(project, input=f"y\n{team}\n")
    assert "Turn it on for everyone who works in this repository?" in out
    assert ("SeamSpec will run these instead:" in out) is (scope == "project")
    assert f"plugin install seamspec@seamspec --scope {scope} --json" in calls(fake_claude)


def test_terminal_never_asks_about_the_team_for_a_checkout(
    fake_claude: Path, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("seamspec.cli._interactive", lambda: True)
    out = init(project, input="y\n")
    assert "Turn it on for everyone" not in out
    assert "plugin install seamspec@seamspec --scope local --json" in calls(fake_claude)


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
