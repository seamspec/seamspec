"""Locked rule: the plugin wrappers and the git pre-commit hook never run a `seamspec` planted in
the current folder, even when PATH is empty (ADR-20261005-9b8f)."""

import subprocess
from pathlib import Path

import pytest

import seamspec
from seamspec.installers.git_hooks import render_hook

CHECKOUT = Path(seamspec.__file__).resolve().parents[1]


@pytest.mark.parametrize("script", ["plugin-hook", "plugin-mcp", "pre-commit"])
def test_no_current_folder_lookup(tmp_path: Path, script: str) -> None:
    planted = tmp_path / "seamspec"
    planted.write_text('#!/bin/sh\necho "PLANTED"\n')
    planted.chmod(0o755)
    if script == "pre-commit":
        path = tmp_path / "pre-commit"
        path.write_text(render_hook(""))
    else:
        path = CHECKOUT / "seamspec-plugin/scripts" / ("seamspec-hook" if script == "plugin-hook" else "seamspec-mcp")
    result = subprocess.run(
        ["/bin/sh", str(path), "hook", "claude", "stop"],
        cwd=tmp_path, capture_output=True, text=True, env={"PATH": "", "HOME": str(tmp_path / "home")},
    )  # fmt: skip
    assert "PLANTED" not in result.stdout + result.stderr
