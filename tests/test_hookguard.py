"""The hook guard for approvals in chat, and the ConfigChange hook built on it (ADR-20261006-c300, guard 1)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from seamspec.adapters import claude
from seamspec.core import hookguard
from seamspec.core.store import Store

from .test_claude_adapter import set_config

REAL_LAUNCH_ARGS = hookguard._launch_args  # before the fixture below replaces it


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hookguard, "MANAGED_DIRS", ())
    monkeypatch.setattr(hookguard, "_launch_args", lambda: [])


def hook_doc(event: str = "Elicitation", matcher: str | None = "*") -> dict[str, Any]:
    group: dict[str, Any] = {"hooks": [{"type": "command", "command": "true"}]}
    if matcher is not None:
        group["matcher"] = matcher
    return {"hooks": {event: [group]}}


def write(path: Path, doc: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc))
    return path


@pytest.mark.parametrize(
    ("matcher", "matches"),
    [(None, True), ("", True), ("*", True), ("plugin:seamspec:seamspec", True), ("plugin:.*", True),
     ("seam", False), ("seamspec", False), ("seamspec|github", False), ("seamspec, github", False),
     ("^seamspec$", False), ("other|plugin:seamspec:seamspec", True), ("[", True), (3, True)],
)  # fmt: skip
def test_matchers_follow_claude_codes_rules(matcher: object, matches: bool) -> None:
    """Exact names when only letters, digits, _ - space , | are used; else an unanchored regex (verified: a
    bare `seamspec` doesn't match the plugin's server). Anything unreadable counts as a match."""
    assert hookguard.matcher_matches(matcher) is matches


def test_settings_in_the_project_and_above_it(tmp_path: Path) -> None:
    project = tmp_path / "work" / "app"
    project.mkdir(parents=True)
    assert hookguard.scan([project]) == []
    write(tmp_path / "work" / ".claude" / "settings.local.json", hook_doc("ElicitationResult"))
    assert "ElicitationResult hook" in hookguard.scan([project])[0]


def test_user_settings_and_unreadable_files(tmp_path: Path) -> None:
    cfg = hookguard.config_dir()
    write(cfg / "settings.json", "{not json")
    assert "can't be read" in hookguard.scan([tmp_path])[0]
    write(cfg / "settings.json", hook_doc(matcher="github"))  # another server: fine
    assert hookguard.scan([tmp_path]) == []


def test_managed_settings_and_drop_ins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    managed = tmp_path / "managed"
    write(managed / "managed-settings.d" / "10-team.json", hook_doc())
    monkeypatch.setattr(hookguard, "MANAGED_DIRS", (managed,))
    assert "10-team.json" in hookguard.scan([tmp_path / "x"])[0]


def test_enabled_plugins_are_checked_where_they_live(tmp_path: Path) -> None:
    plugins = hookguard.config_dir() / "plugins"
    cached = write(tmp_path / "cache" / "other" / "hooks" / "hooks.json", hook_doc()).parents[1]
    write(plugins / "installed_plugins.json", {"plugins": {"other@market": [{"installPath": str(cached)}]}})
    market = tmp_path / "market"
    write(market / ".claude-plugin" / "marketplace.json", {"plugins": [{"name": "local", "source": "./local"}]})
    write(
        market / "local" / ".claude-plugin" / "plugin.json", {"name": "local", "hooks": hook_doc("ElicitationResult")}
    )
    write(plugins / "known_marketplaces.json", {"folder": {"installLocation": str(market)}})
    write(tmp_path / "proj" / ".claude" / "settings.json", {"enabledPlugins": {"other@market": False}})
    assert hookguard.scan([tmp_path / "proj"]) == []  # installed but disabled
    write(
        tmp_path / "proj" / ".claude" / "settings.json",
        {"enabledPlugins": {"other@market": True, "local@folder": True}},
    )
    problems = hookguard.scan([tmp_path / "proj"])
    assert any("cache/other/hooks/hooks.json" in p for p in problems)
    assert any("local/.claude-plugin/plugin.json" in p and "ElicitationResult" in p for p in problems)


def test_skill_and_agent_frontmatter(tmp_path: Path) -> None:
    text = "---\nname: auto\nhooks:\n  Elicitation:\n    - hooks: []\n---\nBody mentions Elicitation too.\n"
    skill = write(tmp_path / ".claude" / "skills" / "auto" / "SKILL.md", text)
    write(tmp_path / ".claude" / "agents" / "ok.md", "---\nname: ok\n---\nElicitation only in the body.\n")
    assert hookguard.scan([tmp_path]) == [f"{skill}: its frontmatter mentions an Elicitation hook, which could "
                                          "answer SeamSpec's dialogs"]  # fmt: skip


def test_launch_arguments(tmp_path: Path) -> None:
    plugin = write(tmp_path / "p" / "hooks" / "hooks.json", hook_doc()).parents[1]
    settings = write(tmp_path / "s.json", hook_doc(matcher=None))
    assert len(hookguard.scan([tmp_path / "x"], [f"claude --plugin-dir {plugin} --settings={settings}"])) == 2
    inline = 'claude --settings {"hooks":{"Elicitation":[{"hooks":[]}]}}'
    assert "started with settings" in hookguard.scan([tmp_path / "x"], [inline])[0]


def test_launch_args_read_the_parent_processes() -> None:
    if os.name == "nt":
        pytest.skip("uses ps")
    lines = REAL_LAUNCH_ARGS()  # whatever started this test run
    assert lines and all(isinstance(line, str) and line for line in lines)


# --- ConfigChange ----------------------------------------------------------------------------------


def config_change(root: Path, path: Path | None, source: str = "local_settings") -> dict[str, Any] | None:
    payload: dict[str, Any] = {"session_id": "s1", "cwd": str(root), "source": source}
    if path is not None:
        payload["file_path"] = str(path)
    out = claude.main("config-change", json.dumps(payload))
    return json.loads(out) if out else None


def test_config_change_blocks_a_new_dialog_hook(git_repo: Path) -> None:
    settings = write(git_repo / ".claude" / "settings.local.json", {"permissions": {"allow": []}})
    assert config_change(git_repo, settings) is None  # an ordinary change
    write(settings, hook_doc())
    out = config_change(git_repo, settings)
    assert out is not None and out["decision"] == "block"
    lines = (Store(git_repo).local / "journal.jsonl").read_text().splitlines()
    assert json.loads(lines[-1])["event"] == "config_change_blocked"
    skill = write(git_repo / ".claude" / "skills" / "x" / "SKILL.md", "---\nhooks:\n  ElicitationResult: []\n---\n")
    assert config_change(git_repo, skill, "skills") is not None
    assert config_change(git_repo, settings, "policy_settings") is None  # can't be blocked anyway


def test_hooks_present_at_session_start_are_left_alone(git_repo: Path) -> None:
    """Chat approvals are refused while they exist; blocking every later edit of that file would only hurt."""
    settings = write(git_repo / ".claude" / "settings.local.json", hook_doc())
    claude.main("session-start", json.dumps({"session_id": "s1", "cwd": str(git_repo), "source": "startup"}))
    assert config_change(git_repo, settings) is None
    write(settings, {**hook_doc(), "permissions": {"allow": ["Bash(ls)"]}})
    assert config_change(git_repo, settings) is None
    write(settings, {"hooks": {**hook_doc()["hooks"], **hook_doc("ElicitationResult")["hooks"]}})
    assert config_change(git_repo, settings) is not None  # a second, new hook


def test_config_change_is_off_without_chat_approvals(git_repo: Path) -> None:
    set_config(git_repo, "[review]\nchat_approvals = true", "[review]\nchat_approvals = false")
    settings = write(git_repo / ".claude" / "settings.local.json", hook_doc())
    assert config_change(git_repo, settings) is None
