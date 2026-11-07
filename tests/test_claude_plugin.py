"""`seamspec init` installs the Claude Code plugin through `claude plugin ...` (SPEC §16.1)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest
from typer.testing import CliRunner

from seamspec.cli import app
from seamspec.core import doctor
from seamspec.installers import claude_plugin

runner = CliRunner()
CHECKOUT = Path(__file__).resolve().parents[1]

FAKE = """#!/bin/sh
echo "$*" >> "$FAKE_CLAUDE_LOG"
case "$*" in
  "plugin list --json") cat "$FAKE_CLAUDE_LIST" 2>/dev/null || echo "[]" ;;
  *"$FAKE_CLAUDE_FAIL"*) echo '{"outcome":"error","message":"boom"}'; exit 1 ;;
  "plugin update"*)
    if [ -f "$FAKE_CLAUDE_LIST.after" ]; then cp "$FAKE_CLAUDE_LIST.after" "$FAKE_CLAUDE_LIST"; fi
    echo '{"outcome":"ok","message":"updated"}' ;;
  "plugin marketplace add"*)
    mkdir -p .claude
    settings=.claude/settings.local.json; [ "$6" = project ] && settings=.claude/settings.json
    case "$4" in
      *://*"#"*) printf '{"extraKnownMarketplaces":{"seamspec":{"source":{"source":"git","url":"%s","ref":"%s"}}}}' \
        "${4%%#*}" "${4#*#}" > "$settings" ;;
      *) [ -f "$settings" ] || echo '{}' > "$settings" ;;
    esac
    echo '{"outcome":"ok","message":"added"}' ;;
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
    subprocess.run(["git", "init", "-q", str(root)], check=True)  # a project; init asks first outside git
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


# --- an upgrade moves the pin (ADR-20261105-bf19) --------------------------------------------------


REPO_URL = "https://github.com/seamspec/seamspec.git"


def installed(project: Path, tmp_path: Path, version: str = "0.1.0", ref: str = "v0.1.0", scope: str = "local") -> None:
    """The plugin as `seamspec init` left it at an earlier version: settings pin plus Claude Code's list."""
    settings = {
        "extraKnownMarketplaces": {"seamspec": {"source": {"source": "git", "url": REPO_URL, "ref": ref}}},
        "enabledPlugins": {"seamspec@seamspec": True},
    }
    (project / ".claude").mkdir(exist_ok=True)
    (project / claude_plugin.SETTINGS[scope]).write_text(json.dumps(settings))
    entry = {
        "id": "seamspec@seamspec",
        "version": version,
        "scope": scope,
        "enabled": True,
        "projectPath": str(project),
    }
    (tmp_path / "list.json").write_text(json.dumps([entry]))


def moves_to(project: Path, tmp_path: Path, version: str, scope: str = "local") -> None:
    """The copy the fake `claude plugin update` leaves behind; its `marketplace add` moves the pin."""
    entry = {
        "id": "seamspec@seamspec",
        "version": version,
        "scope": scope,
        "enabled": True,
        "projectPath": str(project),
    }
    (tmp_path / "list.json.after").write_text(json.dumps([entry]))


@pytest.fixture
def next_release(released_build: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """The same install after `uv tool upgrade seamspec`."""
    monkeypatch.setattr(claude_plugin, "__version__", "0.1.1")
    return f"{REPO_URL}#v0.1.1"


def test_a_new_version_finds_the_old_pin(fake_claude: Path, project: Path, tmp_path: Path, next_release: str) -> None:
    installed(project, tmp_path)
    found = claude_plugin.upgrades(project)
    assert [(u.scope, u.pinned_ref, u.version, u.source) for u in found] == [("local", "v0.1.0", "0.1.0", next_release)]


def test_upgrade_moves_the_pin_then_updates_the_plugin(
    fake_claude: Path, project: Path, tmp_path: Path, next_release: str
) -> None:
    installed(project, tmp_path)
    moves_to(project, tmp_path, "0.1.1")
    result = claude_plugin.install(project)
    assert result.status == "upgraded" and "v0.1.1" in result.message
    assert calls(fake_claude)[1:3] == [
        f"plugin marketplace add {next_release} --scope local --json",
        "plugin update seamspec@seamspec --scope local --json",
    ]
    assert claude_plugin.upgrades(project) == []


def test_the_matching_version_is_left_alone(
    fake_claude: Path, project: Path, tmp_path: Path, released_build: str
) -> None:
    installed(project, tmp_path)
    assert claude_plugin.upgrades(project) == []
    assert claude_plugin.install(project).status == "unchanged"
    assert not any("marketplace add" in call or "update" in call for call in calls(fake_claude))


def test_a_pin_already_moved_by_a_teammate_still_updates_this_copy(
    fake_claude: Path, project: Path, tmp_path: Path, next_release: str
) -> None:
    """A teammate committed the new tag; this machine still has the old plugin."""
    installed(project, tmp_path, version="0.1.0", ref="v0.1.1", scope="project")
    assert [(u.scope, u.version) for u in claude_plugin.upgrades(project)] == [("project", "0.1.0")]


def test_project_scope_moves_the_committed_pin(
    fake_claude: Path, project: Path, tmp_path: Path, next_release: str
) -> None:
    installed(project, tmp_path, scope="project")
    moves_to(project, tmp_path, "0.1.1", scope="project")
    result = claude_plugin.install(project, "project")
    assert result.status == "upgraded" and ".claude/settings.json" in result.message
    assert "plugin update seamspec@seamspec --scope project --json" in calls(fake_claude)
    settings = json.loads((project / ".claude/settings.json").read_text())
    assert settings["extraKnownMarketplaces"]["seamspec"]["source"]["ref"] == "v0.1.1"


def test_a_failed_move_is_reported(
    fake_claude: Path, project: Path, tmp_path: Path, next_release: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed(project, tmp_path)
    monkeypatch.setenv("FAKE_CLAUDE_FAIL", "plugin update")
    result = claude_plugin.install(project)
    assert result.status == "failed" and "claude plugin update" in result.message and "boom" in result.message


def test_a_move_that_changes_nothing_is_not_called_success(
    fake_claude: Path, project: Path, tmp_path: Path, next_release: str
) -> None:
    """Every command says ok but the plugin stays put: say so, don't report it as moved."""
    installed(project, tmp_path)
    result = claude_plugin.install(project)
    assert result.status == "failed" and "didn't move" in result.message and "0.1.0" in result.message


def test_a_failed_check_afterwards_is_not_called_success(
    fake_claude: Path, project: Path, tmp_path: Path, next_release: str
) -> None:
    """`claude plugin list` breaks after the update: unknown isn't the same as moved."""
    installed(project, tmp_path)
    (tmp_path / "list.json.after").write_text("not json")
    result = claude_plugin.install(project)
    assert result.status == "failed" and "can't confirm" in result.message


def test_plugin_scope_local_never_moves_the_committed_pin(
    fake_claude: Path, project: Path, tmp_path: Path, next_release: str
) -> None:
    installed(project, tmp_path, scope="project")
    before = (project / ".claude/settings.json").read_text()
    out = init(project, "--plugin", "--plugin-scope", "local")
    assert "upgraded" not in out and (project / ".claude/settings.json").read_text() == before
    assert not any("--scope project" in call for call in calls(fake_claude))


@pytest.mark.parametrize("url", ["https://github.com/someone/fork.git", "https://example.com/seamspec.git"])
def test_a_pin_to_another_repository_is_left_alone(
    fake_claude: Path, project: Path, tmp_path: Path, next_release: str, url: str
) -> None:
    installed(project, tmp_path)
    settings = json.loads((project / ".claude/settings.local.json").read_text())
    settings["extraKnownMarketplaces"]["seamspec"]["source"]["url"] = url
    (project / ".claude/settings.local.json").write_text(json.dumps(settings))
    assert claude_plugin.upgrades(project) == []


def test_a_checkout_never_moves_a_pin(fake_claude: Path, project: Path, tmp_path: Path) -> None:
    installed(project, tmp_path)
    assert claude_plugin.upgrades(project) == []
    assert calls(fake_claude) == []  # and without running `claude`


def test_a_user_scope_install_is_left_alone(
    fake_claude: Path, project: Path, tmp_path: Path, next_release: str
) -> None:
    """It covers every project on the machine, so one repository's `init` doesn't change it."""
    installed(project, tmp_path)
    entry = {"id": "seamspec@seamspec", "version": "0.1.0", "scope": "user", "enabled": True}
    (tmp_path / "list.json").write_text(json.dumps([entry]))
    assert claude_plugin.upgrades(project) == []


def test_no_pin_here_runs_nothing(fake_claude: Path, project: Path, next_release: str) -> None:
    assert claude_plugin.upgrades(project) == []
    assert calls(fake_claude) == []


@pytest.mark.parametrize("answer", ["y", "n"])
def test_init_asks_before_moving_it(
    fake_claude: Path, project: Path, tmp_path: Path, next_release: str, monkeypatch: pytest.MonkeyPatch, answer: str
) -> None:
    monkeypatch.setattr("seamspec.cli._interactive", lambda: True)
    installed(project, tmp_path)
    moves_to(project, tmp_path, "0.1.1")
    out = init(project, input=f"{answer}\n")
    assert f"claude plugin marketplace add {next_release} --scope local" in out
    assert "claude plugin update seamspec@seamspec --scope local" in out
    assert ("Claude Code plugin: upgraded" in out) is (answer == "y")
    assert ("Restart Claude Code" in out) is (answer == "y")
    assert ("not moved" in out) is (answer == "n")
    assert any("plugin update" in call for call in calls(fake_claude)) is (answer == "y")


def test_init_plugin_flag_moves_it_without_asking(
    fake_claude: Path, project: Path, tmp_path: Path, next_release: str
) -> None:
    installed(project, tmp_path)
    moves_to(project, tmp_path, "0.1.1")
    assert "Claude Code plugin: upgraded" in init(project, "--plugin")


def test_init_without_a_terminal_never_moves_it(
    fake_claude: Path, project: Path, tmp_path: Path, next_release: str
) -> None:
    installed(project, tmp_path)
    out = init(project)
    assert "seamspec init --plugin" in out and calls(fake_claude) == []


def test_init_says_to_commit_a_moved_team_pin(
    fake_claude: Path, project: Path, tmp_path: Path, next_release: str
) -> None:
    installed(project, tmp_path, scope="project")
    moves_to(project, tmp_path, "0.1.1", scope="project")
    assert "Commit .claude/settings.json" in init(project, "--plugin")


def test_doctor_warns_about_an_old_plugin(fake_claude: Path, project: Path, tmp_path: Path, next_release: str) -> None:
    init(project)
    installed(project, tmp_path)
    report = doctor.run(project)
    found = [f for f in report.findings if f.check == "claude plugin"]
    assert [f.level for f in found] == ["warning"] and "seamspec init --plugin" in found[0].message
    assert "claude plugin" in report.checks


def test_doctor_is_quiet_when_the_plugin_matches(
    fake_claude: Path, project: Path, tmp_path: Path, released_build: str
) -> None:
    init(project)
    installed(project, tmp_path)
    assert not [f for f in doctor.run(project).findings if f.check == "claude plugin"]


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


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def plugin_server(tmp_path: Path) -> Iterator[str]:
    """A marketplace with tags v1.0.0 and v1.0.1, served over HTTP by `git http-backend`: Claude Code
    only clones real git servers, and SeamSpec's next tag doesn't exist until it is released."""
    work = tmp_path / "market"
    (work / ".claude-plugin").mkdir(parents=True)
    (work / "plugin/.claude-plugin").mkdir(parents=True)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-C", str(work)]
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    marketplace = {
        "name": "seamspec",
        "owner": {"name": "t"},
        "plugins": [{"name": "seamspec", "source": "./plugin", "description": "t"}],
    }
    (work / ".claude-plugin/marketplace.json").write_text(json.dumps(marketplace))
    for version in ("1.0.0", "1.0.1"):
        plugin = {"name": "seamspec", "version": version, "description": "t"}
        (work / "plugin/.claude-plugin/plugin.json").write_text(json.dumps(plugin))
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-qm", version], check=True)
        subprocess.run([*git, "tag", f"v{version}"], check=True)
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(tmp_path / "market.git")], check=True)

    def app_(environ: dict, start_response):  # type: ignore[no-untyped-def]
        length = int(environ.get("CONTENT_LENGTH") or 0)
        env = {
            **os.environ,
            "GIT_PROJECT_ROOT": str(tmp_path),
            "GIT_HTTP_EXPORT_ALL": "1",
            "PATH_INFO": environ["PATH_INFO"],
            "QUERY_STRING": environ.get("QUERY_STRING", ""),
            "REQUEST_METHOD": environ["REQUEST_METHOD"],
            "CONTENT_TYPE": environ.get("CONTENT_TYPE", ""),
            "CONTENT_LENGTH": str(length),
            "REMOTE_ADDR": "127.0.0.1",
        }
        for name, var in (("HTTP_GIT_PROTOCOL", "GIT_PROTOCOL"), ("HTTP_CONTENT_ENCODING", "HTTP_CONTENT_ENCODING")):
            if environ.get(name):
                env[var] = environ[name]
        body = environ["wsgi.input"].read(length) if length else b""
        out = subprocess.run(["git", "http-backend"], input=body, capture_output=True, env=env).stdout
        head, _, rest = out.partition(b"\r\n\r\n")
        headers = [tuple(line.decode().split(": ", 1)) for line in head.split(b"\r\n") if b": " in line]
        status = next((value for name, value in headers if name == "Status"), "200 OK")
        start_response(status, [(name, value) for name, value in headers if name != "Status"])
        return [rest]

    server = make_server("127.0.0.1", 0, app_, handler_class=_QuietHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/market.git"
    server.shutdown()
    server.server_close()


@pytest.mark.skipif(shutil.which("claude") is None, reason="Claude Code CLI not installed")
def test_real_claude_cli_moves_the_pin_and_updates_the_plugin(
    project: Path, plugin_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    monkeypatch.setenv(claude_plugin.SOURCE_ENV, f"{plugin_server}#v1.0.0")
    first = claude_plugin.install(project)
    assert first.status == "installed", first.message
    assert claude_plugin.upgrades(project) == []

    monkeypatch.setenv(claude_plugin.SOURCE_ENV, f"{plugin_server}#v1.0.1")  # the upgrade
    assert [(u.pinned_ref, u.version) for u in claude_plugin.upgrades(project)] == [("v1.0.0", "1.0.0")]
    moved = claude_plugin.install(project)
    assert moved.status == "upgraded", moved.message
    assert claude_plugin.upgrades(project) == []
    settings = json.loads((project / ".claude/settings.local.json").read_text())
    assert settings["extraKnownMarketplaces"]["seamspec"]["source"]["ref"] == "v1.0.1"
    versions = [p["version"] for p in claude_plugin._enabled_entries(project)]
    assert versions == ["1.0.1"]
