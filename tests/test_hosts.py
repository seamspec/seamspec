"""Cursor, VS Code (Copilot) and Antigravity (SPEC §16.2–§16.4, ADR-20261013-e8f3): project files that
are merged, never overwritten, and hooks that speak each host's documented format."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from seamspec.adapters import hosts as adapter
from seamspec.cli import app
from seamspec.core import commands
from seamspec.installers import directive
from seamspec.installers import hosts as installer

from .test_claude_adapter import BROKEN_CODE, lock

runner = CliRunner()
HOSTS = ("cursor", "vscode", "antigravity")


@pytest.fixture
def human(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")


# --- commands and rules -----------------------------------------------------------------------------


@pytest.mark.parametrize("host", HOSTS)
def test_commands_are_rendered_in_each_hosts_format(host: str) -> None:
    names = commands.commands_for(host)
    assert "drain" in names and "lock" in names
    assert ("explain" in names) == (host in commands.REVIEWER_HOSTS)  # Cursor can't run a read-only reviewer yet
    for name in names:
        text = commands.render(name, host)
        assert "/seamspec:" not in text
        assert (
            "seamspec review" in text
            or name in ("context", "status", "dead-end")
            or (host, name)
            == (
                "vscode",
                "explain",
            )
        )
        assert "$ARGUMENTS" not in text and "{{args}}" not in text
        if host == "vscode":
            front = text.split("\n---\n", 1)[0].splitlines()[1:]
            meta = {
                k: json.loads(v) for k, v in (line.split(": ", 1) for line in front if not line.startswith("agent"))
            }
            assert meta["description"]
        if host == "antigravity":
            assert text.startswith(f"---\nname: seamspec-{name}\ndescription: ")
    with pytest.raises(ValueError):
        commands.render("explain", "cursor")


def test_reviewer_is_read_only_in_vscode_and_antigravity(tmp_path: Path) -> None:
    """ADR-20261015-4f7b: a separate agent that didn't write the rules, limited to reading."""
    vscode = commands.render_agent("reviewer", "vscode")
    front = vscode.split("\n---\n", 1)[0]
    assert "name: seamspec-reviewer" in front and "agents: []" in front
    assert "tools: ['read', 'search', 'seamspec/review_material']" in front  # nothing that edits or runs
    prompt = commands.render("explain", "vscode")
    assert "agent: seamspec-reviewer" in prompt and "Explain the items waiting for SeamSpec review" in prompt

    antigravity = commands.render_agent("reviewer", "antigravity")
    front = antigravity.split("\n---\n", 1)[0]
    assert "  - view_file\n  - grep_search\n" in front and 'commandExecutionPolicy: "off"' in front
    assert "run_command" not in front and "replace_file_content" not in front and "mainAgent: false" in front
    skill = commands.render("explain", "antigravity")
    assert "invoke_subagent" in skill and "`seamspec-reviewer`" in skill and "in full and unchanged" in skill
    for text in (vscode, antigravity):  # without SeamSpec's tool it can still find every item itself
        assert ".seamspec/invariants/inv_*.json" in text and ".seamspec/.local/requests/" in text
        assert "You are SeamSpec's reviewer" in text
    with pytest.raises(ValueError):
        commands.render_agent("reviewer", "cursor")

    for host in commands.REVIEWER_HOSTS:
        changes = {c.path: c.status for c in installer.install(tmp_path / host, host)}
        rel = commands.AGENT_FILES[host].format(name="reviewer")
        assert changes[rel] == "created" and (tmp_path / host / rel).read_text() == commands.render_agent(
            "reviewer", host
        )
        assert (tmp_path / host / commands.HOST_FILES[host].format(name="explain")).is_file()
        assert {c.status for c in installer.install(tmp_path / host, host)} == {"unchanged"}
    installer.install(tmp_path / "cursor", "cursor")
    assert not (tmp_path / "cursor/.cursor/commands/seamspec-explain.md").exists()


def test_agents_md_gets_the_protocol_worded_for_these_hosts(tmp_path: Path) -> None:
    text = directive.directive_text("agents")
    assert "/seamspec-drain" in text and "/seamspec:" not in text
    assert "SeamSpec's reviewer (`/seamspec-explain`, where your tool has it)" in text  # not Cursor yet
    assert "Only humans approve invariants" in text and "never answer its prompts" in text
    (tmp_path / "AGENTS.md").write_text("# Our agents\n\nUse tabs.\n")
    assert directive.install(tmp_path, directive.AGENTS_FILE) == "updated"
    assert (tmp_path / "AGENTS.md").read_text().startswith("# Our agents\n\nUse tabs.\n")
    assert not directive.drift(tmp_path, directive.AGENTS_FILE) and directive.drift(tmp_path)  # CLAUDE.md: absent
    assert directive.foreign_lines(directive.render_block("agents")) == []  # its own lines are known


# --- installing -------------------------------------------------------------------------------------


@pytest.mark.parametrize("host", HOSTS)
def test_install_writes_rules_tools_hooks_and_commands_then_changes_nothing(tmp_path: Path, host: str) -> None:
    changes = installer.install(tmp_path, host)
    assert {c.status for c in changes} == {"created"}
    mcp_rel, keys, server = installer.mcp_entry(host, tmp_path)
    assert json.loads((tmp_path / mcp_rel).read_text())[keys[0]][keys[1]] == server
    hooks_rel, _ = installer.hook_entries(host)
    hooks_text = (tmp_path / hooks_rel).read_text()
    assert f"seamspec hook {host} session-start" in hooks_text and f"seamspec hook {host} stop" in hooks_text
    assert (tmp_path / commands.HOST_FILES[host].format(name="lock")).is_file()
    assert {c.status for c in installer.install(tmp_path, host)} == {"unchanged"}  # a rerun


def test_antigravity_server_is_told_the_project_folder(tmp_path: Path) -> None:
    """Antigravity starts the server in `/` and can't answer its roots/list question (hands-on test)."""
    installer.install(tmp_path, "antigravity")
    server = json.loads((tmp_path / ".agents/mcp_config.json").read_text())["mcpServers"]["seamspec"]
    assert server["env"] == {"SEAMSPEC_ROOT": str(tmp_path.resolve())}


def test_an_older_antigravity_entry_gets_the_folder_and_keeps_the_rest(tmp_path: Path) -> None:
    (tmp_path / ".agents").mkdir()
    old = {"mcpServers": {"seamspec": {"command": "seamspec", "args": ["mcp"], "env": {"SEAMSPEC_DEBUG": "1"}},
                          "db": {"command": "dbmcp"}}}  # fmt: skip
    (tmp_path / ".agents/mcp_config.json").write_text(json.dumps(old))
    assert installer.install_mcp(tmp_path, "antigravity").status == "updated"
    servers = json.loads((tmp_path / ".agents/mcp_config.json").read_text())["mcpServers"]
    assert servers["seamspec"]["env"] == {"SEAMSPEC_DEBUG": "1", "SEAMSPEC_ROOT": str(tmp_path.resolve())}
    assert servers["db"] == {"command": "dbmcp"}
    moved = tmp_path / "elsewhere"
    shutil.copytree(tmp_path / ".agents", moved / ".agents")  # a clone in another folder
    assert installer.install_mcp(moved, "antigravity").status == "updated"
    env = json.loads((moved / ".agents/mcp_config.json").read_text())["mcpServers"]["seamspec"]["env"]
    assert env["SEAMSPEC_ROOT"] == str(moved.resolve())


def test_doctor_warns_when_antigravity_points_at_another_folder(tmp_path: Path) -> None:
    from seamspec.core import doctor
    from seamspec.installers import scaffold

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    scaffold.init(tmp_path, auto_run=True, actor="Maya <maya@example.com>")
    installer.install(tmp_path, "antigravity")
    assert not [f for f in doctor.run(tmp_path).findings if f.check == "antigravity"]
    config = tmp_path / ".agents/mcp_config.json"
    data = json.loads(config.read_text())
    data["mcpServers"]["seamspec"]["env"]["SEAMSPEC_ROOT"] = "/Users/someone-else/project"  # a teammate's clone
    config.write_text(json.dumps(data))
    found = [f for f in doctor.run(tmp_path).findings if f.check == "antigravity"]
    assert found and "/Users/someone-else/project" in found[0].message and found[0].level == "warning"


def test_someone_elses_seamspec_entry_is_kept(tmp_path: Path) -> None:
    (tmp_path / ".agents").mkdir()
    mine = {"mcpServers": {"seamspec": {"command": "/opt/seamspec/bin/seamspec", "args": ["mcp"]}}}
    (tmp_path / ".agents/mcp_config.json").write_text(json.dumps(mine))
    assert installer.install_mcp(tmp_path, "antigravity").status == "kept (yours)"


def test_install_keeps_what_is_already_there(tmp_path: Path) -> None:
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor/mcp.json").write_text(json.dumps({"mcpServers": {"db": {"command": "dbmcp"}}}))
    (tmp_path / ".cursor/hooks.json").write_text(json.dumps(
        {"version": 1, "hooks": {"stop": [{"command": "./lint.sh"}], "afterFileEdit": [{"command": "./fmt.sh"}]}}
    ))  # fmt: skip
    installer.install(tmp_path, "cursor")
    mcp = json.loads((tmp_path / ".cursor/mcp.json").read_text())["mcpServers"]
    assert mcp["db"] == {"command": "dbmcp"} and "seamspec" in mcp
    hooks = json.loads((tmp_path / ".cursor/hooks.json").read_text())["hooks"]
    assert hooks["stop"][0] == {"command": "./lint.sh"} and hooks["stop"][1]["command"] == "seamspec hook cursor stop"
    assert hooks["afterFileEdit"] == [{"command": "./fmt.sh"}]
    # Someone tuned SeamSpec's own server entry, or broke a file: both are left alone.
    mcp["seamspec"] = {"command": "/opt/seamspec/bin/seamspec", "args": ["mcp"]}
    (tmp_path / ".cursor/mcp.json").write_text(json.dumps({"mcpServers": mcp}))
    (tmp_path / ".cursor/hooks.json").write_text("{ not json")
    statuses = {c.path: c.status for c in installer.install(tmp_path, "cursor")}
    assert statuses[".cursor/mcp.json"] == "kept (yours)"
    assert (
        statuses[".cursor/hooks.json"].startswith("skipped")
        and (tmp_path / ".cursor/hooks.json").read_text() == "{ not json"
    )


def test_detect_finds_the_hosts_folders(tmp_path: Path) -> None:
    assert installer.detect(tmp_path) == []
    (tmp_path / ".vscode").mkdir()
    (tmp_path / ".agent").mkdir()  # Antigravity's older folder name
    assert installer.detect(tmp_path) == ["vscode", "antigravity"]


# --- hooks in each host's format ----------------------------------------------------------------------


def payload(host: str, event: str, root: Path, **extra) -> str:
    if host == "antigravity":
        base = {"conversationId": "c1", "workspacePaths": [str(root)]}
        if event == "stop":
            base |= {"fullyIdle": True, "terminationReason": "model_stop", "executionNum": 1}
    elif host == "vscode":
        base = {"cwd": str(root), "session_id": "s1", "hook_event_name": "Stop" if event == "stop" else "SessionStart"}
        base |= {"stop_hook_active": False} if event == "stop" else {"source": "new"}
    else:
        base = {"session_id": "s1", "cwd": str(root)} | (
            {"status": "completed", "loop_count": 0} if event == "stop" else {}
        )
    return json.dumps(base | extra)


@pytest.mark.parametrize("host", HOSTS)
def test_session_start_gives_the_rules_in_force(git_repo: Path, human: None, host: str) -> None:
    inv_id = lock(git_repo)
    out = json.loads(adapter.main(host, "session-start", payload(host, "session-start", git_repo)))
    text = {
        "cursor": lambda o: o["additional_context"],
        "vscode": lambda o: o["hookSpecificOutput"]["additionalContext"],
        "antigravity": lambda o: o["injectSteps"][0]["systemMessage"]["systemMessage"],
    }[host](out)
    assert inv_id in text and "Retry delay" in text


@pytest.mark.parametrize("host", HOSTS)
def test_stop_sends_the_agent_back_when_a_locked_rule_fails(git_repo: Path, human: None, host: str) -> None:
    inv_id = lock(git_repo)
    assert adapter.main(host, "stop", payload(host, "stop", git_repo)) == ""  # green: nothing to say
    (git_repo / "src/queue.py").write_text(BROKEN_CODE)
    out = json.loads(adapter.main(host, "stop", payload(host, "stop", git_repo)))
    reason = {
        "cursor": lambda o: o["followup_message"],
        "vscode": lambda o: o["hookSpecificOutput"]["reason"] if o["hookSpecificOutput"]["decision"] == "block" else "",
        "antigravity": lambda o: o["reason"] if o["decision"] == "continue" else "",
    }[host](out)
    assert inv_id in reason and "request_supersede" in reason


def test_vscode_hooks_also_load_in_the_copilot_agent(git_repo: Path, human: None, tmp_path: Path) -> None:
    """VS Code's chats ran in the Copilot agent, which ignored the hook file: it rejects a file with no
    `version` (hands-on test, 2026-10-16, ADR-20261016-2d9a)."""
    installer.install(tmp_path, "vscode")
    data = json.loads((tmp_path / ".github/hooks/seamspec.json").read_text())
    assert data["version"] == 1
    assert data["hooks"]["Stop"][0]["timeoutSec"] == data["hooks"]["Stop"][0]["timeout"] == installer.STOP_TIMEOUT

    old = tmp_path / "old"
    (old / ".github/hooks").mkdir(parents=True)
    (old / ".github/hooks/seamspec.json").write_text(json.dumps({"hooks": {
        "SessionStart": [{"type": "command", "command": "seamspec hook vscode session-start", "timeout": 30}],
        "Stop": [{"type": "command", "command": "seamspec hook vscode stop", "timeout": 120}],
    }}))  # fmt: skip
    assert installer.install_hooks(old, "vscode").status == "updated"
    data = json.loads((old / ".github/hooks/seamspec.json").read_text())
    assert data["version"] == 1 and data["hooks"]["Stop"] == [
        {"type": "command", "command": "seamspec hook vscode stop", "timeout": 120, "timeoutSec": 120}
    ]  # a hand-tuned timeout carries over

    inv_id = lock(git_repo)
    camel = json.dumps({"sessionId": "s9", "cwd": str(git_repo), "stopHookActive": False})  # the Copilot agent's own
    (git_repo / "src/queue.py").write_text(BROKEN_CODE)
    out = json.loads(adapter.main("vscode", "stop", camel))
    assert out["decision"] == "block" and inv_id in out["reason"]  # what the Copilot agent reads
    assert out["hookSpecificOutput"]["decision"] == "block"  # what VS Code's Local agent reads
    start = json.loads(adapter.main("vscode", "session-start", payload("vscode", "session-start", git_repo)))
    assert (
        inv_id in start["additionalContext"]
        and start["additionalContext"] == start["hookSpecificOutput"]["additionalContext"]
    )


def test_stop_is_capped_and_waits_for_background_work(git_repo: Path, human: None) -> None:
    lock(git_repo)
    (git_repo / "src/queue.py").write_text(BROKEN_CODE)
    assert adapter.main("antigravity", "stop", payload("antigravity", "stop", git_repo, fullyIdle=False)) == ""
    blocks = [adapter.main("antigravity", "stop", payload("antigravity", "stop", git_repo)) for _ in range(5)]
    assert [bool(b) for b in blocks] == [True, True, True, False, False]  # verify.max_stop_retries = 3


def test_hook_command_line_and_bad_input(git_repo: Path, human: None) -> None:
    lock(git_repo)
    (git_repo / "src/queue.py").write_text(BROKEN_CODE)
    out = runner.invoke(app, ["hook", "cursor", "stop"], input=payload("cursor", "stop", git_repo))
    assert out.exit_code == 0 and "followup_message" in out.output
    broken = runner.invoke(app, ["hook", "cursor", "stop"], input="not json")  # fail open: no decision, only a note
    assert broken.exit_code == 0 and "followup_message" not in broken.output and "seamspec hook error" in broken.output
    assert "unknown event" in runner.invoke(app, ["hook", "vscode", "pre-tool-use"], input="{}").output


def test_init_hosts_option(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "pyproject.toml").write_text("")
    out = runner.invoke(app, ["init", "--path", str(tmp_path), "--hosts", "cursor,antigravity"])
    assert "MCP servers in Copilot" not in out.output  # VS Code's notes only when VS Code is set up
    assert out.exit_code == 0, out.output
    assert "Cursor:" in out.output and "Antigravity:" in out.output and "VS Code" not in out.output
    assert (tmp_path / ".cursor/hooks.json").is_file() and (tmp_path / ".agents/hooks.json").is_file()
    assert "seamspec hook vscode" not in (tmp_path / "AGENTS.md").read_text()
    bad = runner.invoke(app, ["init", "--path", str(tmp_path), "--hosts", "emacs"])
    assert bad.exit_code == 1 and "unknown tool" in bad.output
    (tmp_path / ".vscode").mkdir()
    quiet = runner.invoke(app, ["init", "--path", str(tmp_path)])  # no terminal: never installs on its own
    assert "run `seamspec init --hosts" in quiet.output and not (tmp_path / ".vscode/mcp.json").exists()


def test_init_tells_what_to_do_in_vscode(tmp_path: Path) -> None:
    """Org Copilot policies hid hooks and MCP in the owner's VS Code (hands-on test, 2026-10-16)."""
    (tmp_path / "pyproject.toml").write_text("")
    out = runner.invoke(app, ["init", "--path", str(tmp_path), "--hosts", "vscode"])
    assert out.exit_code == 0, out.output
    assert "MCP: List Servers" in out.output and '"Editor preview features"' in out.output
    assert '"MCP servers in Copilot"' in out.output


def test_init_tells_what_to_do_in_cursor(tmp_path: Path) -> None:
    """Cursor left SeamSpec's server off until switched on by hand (hands-on test, 2026-10-17)."""
    (tmp_path / "pyproject.toml").write_text("")
    out = runner.invoke(app, ["init", "--path", str(tmp_path), "--hosts", "cursor"])
    assert out.exit_code == 0, out.output
    assert "switch SeamSpec's server on once" in out.output and "MCP servers in Copilot" not in out.output
