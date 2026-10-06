"""The Claude Code plugin in `seamspec-plugin/` (SPEC §15A.4, §16.1)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from seamspec.core.commands import V01_COMMANDS, render

PLUGIN = Path(__file__).resolve().parents[1] / "seamspec-plugin"


def test_manifest() -> None:
    manifest = json.loads((PLUGIN / ".claude-plugin/plugin.json").read_text())
    assert manifest["name"] == "seamspec"  # every skill and tool is namespaced under it: /seamspec:lock
    assert manifest["license"] == "Apache-2.0" and manifest["version"]


def test_hooks_point_at_executable_wrappers() -> None:
    hooks = json.loads((PLUGIN / "hooks/hooks.json").read_text())["hooks"]
    pre = hooks["PreToolUse"][0]
    assert pre["matcher"] == "Edit|Write|MultiEdit|NotebookEdit"
    commands = [h["command"] for event in hooks.values() for group in event for h in group["hooks"]]
    assert commands == [
        '"${CLAUDE_PLUGIN_ROOT}"/scripts/seamspec-hook hook claude pre-tool-use',
        '"${CLAUDE_PLUGIN_ROOT}"/scripts/seamspec-hook hook claude stop',
    ]
    stop_timeout = hooks["Stop"][0]["hooks"][0]["timeout"]
    assert stop_timeout == 300  # must stay above verify.stop_deadline_seconds (240), SPEC §16.1
    for script in ("seamspec-hook", "seamspec-mcp"):
        assert os.access(PLUGIN / "scripts" / script, os.X_OK)
    assert not (PLUGIN / "bin").exists(), "bin/ would put the wrappers on the agent's PATH"


def test_mcp_config() -> None:
    server = json.loads((PLUGIN / ".mcp.json").read_text())["mcpServers"]["seamspec"]
    assert server["command"] == "${CLAUDE_PLUGIN_ROOT}/scripts/seamspec-mcp"
    assert server["env"] == {"SEAMSPEC_ROOT": "${CLAUDE_PROJECT_DIR}"}


@pytest.mark.parametrize("name", V01_COMMANDS)
def test_skills_match_their_templates(name: str) -> None:
    committed = (PLUGIN / "skills" / name / "SKILL.md").read_text()
    assert committed == render(name), f"skills/{name}/SKILL.md is stale: run `uv run python -m seamspec.core.commands`"
    assert committed.startswith(f"---\nname: {name}\n") and "$ARGUMENTS" in committed
    assert "{{" not in committed


def _path_without_seamspec(tmp_path: Path) -> str:
    """A PATH with the basic tools but no `seamspec`, as on a teammate's machine."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in ("sh", "env"):
        found = shutil.which(tool)
        if found:
            (bindir / tool).symlink_to(found)
    return str(bindir)


def test_hook_wrapper_is_silent_without_the_cli(tmp_path: Path) -> None:
    result = subprocess.run(
        ["/bin/sh", str(PLUGIN / "scripts/seamspec-hook"), "hook", "claude", "stop"],
        input='{"session_id": "s"}', capture_output=True, text=True, env={"PATH": _path_without_seamspec(tmp_path)},
    )  # fmt: skip
    assert result.returncode == 0 and result.stdout == "" and result.stderr == ""


def test_mcp_wrapper_explains_a_missing_cli(tmp_path: Path) -> None:
    result = subprocess.run(
        ["/bin/sh", str(PLUGIN / "scripts/seamspec-mcp")],
        capture_output=True, text=True, env={"PATH": _path_without_seamspec(tmp_path)},
    )  # fmt: skip
    assert (
        result.returncode == 1
        and "uv tool install --force --editable" in result.stderr
        and "uv tool install seamspec" in result.stderr
    )


@pytest.mark.parametrize(("script", "expected"), [("seamspec-hook", "hook claude stop"), ("seamspec-mcp", "mcp")])
def test_wrappers_find_a_uv_tool_install_off_path(tmp_path: Path, script: str, expected: str) -> None:
    """The desktop app and GUI git clients often start without ~/.local/bin on PATH."""
    home_bin = tmp_path / "home/.local/bin"
    home_bin.mkdir(parents=True)
    fake = home_bin / "seamspec"
    fake.write_text('#!/bin/sh\necho "ran: $*"\n')
    fake.chmod(0o755)
    args = ["hook", "claude", "stop"] if script == "seamspec-hook" else []
    result = subprocess.run(
        ["/bin/sh", str(PLUGIN / "scripts" / script), *args],
        capture_output=True, text=True, env={"PATH": _path_without_seamspec(tmp_path), "HOME": str(tmp_path / "home")},
    )  # fmt: skip
    assert result.returncode == 0 and result.stdout.strip() == f"ran: {expected}", result.stderr


@pytest.mark.parametrize("script", ["seamspec-hook", "seamspec-mcp"])
def test_wrappers_never_search_the_current_folder(tmp_path: Path, script: str) -> None:
    """An empty PATH must not become ":~/.local/bin", whose empty entry would run a checkout's ./seamspec."""
    planted = tmp_path / "seamspec"
    planted.write_text('#!/bin/sh\necho "planted"\n')
    planted.chmod(0o755)
    result = subprocess.run(
        ["/bin/sh", str(PLUGIN / "scripts" / script), "hook", "claude", "stop"],
        capture_output=True, text=True, cwd=tmp_path, env={"PATH": "", "HOME": str(tmp_path / "home")},
    )  # fmt: skip
    assert "planted" not in result.stdout


@pytest.mark.skipif(shutil.which("claude") is None, reason="Claude Code CLI not installed")
def test_claude_plugin_validate() -> None:
    result = subprocess.run(["claude", "plugin", "validate", str(PLUGIN)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0 and "Validation passed" in result.stdout + result.stderr, (
        result.stdout + result.stderr
    )
