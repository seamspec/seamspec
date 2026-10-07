"""Locked rule: SeamSpec gives test runs no "under verification" signal (SPEC §12.4.7)."""

from pathlib import Path

from seamspec.core import verifier
from seamspec.core.config import parse_config


def test_seamspec_adds_nothing_but_the_project_tool_path(tmp_path: Path) -> None:
    (tmp_path / ".venv/bin").mkdir(parents=True)
    cfg = parse_config("")
    env = verifier.build_env(cfg, {"HOME": "/home/maya", "GITHUB_TOKEN": "secret"}, root=tmp_path)
    # Only what the user's environment allowed through, plus PATH for the project's own tools.
    assert set(env) == {"HOME", "PATH"}
    assert not [k for k in env if "SEAMSPEC" in k.upper() or "VERIF" in k.upper()]
