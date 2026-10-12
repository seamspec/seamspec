"""Hints for agents writing rule tests: how to import the project, and where the runner's program
comes from (SPEC §12A.6, ADR-20261011-e7c5; dogfooding finding #3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client

from seamspec.core import runners
from seamspec.installers import scaffold
from seamspec.mcp_server import mcp


def package(root: Path, rel: str) -> None:
    (root / rel).mkdir(parents=True, exist_ok=True)
    (root / rel / "__init__.py").write_text("")


def project(root: Path, name: str = "demo") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(f'[project]\nname = "{name}"\n')
    return root


def test_src_layout_imports_the_package_by_name(tmp_path: Path) -> None:
    root = project(tmp_path, "spec-agent")
    package(root, "src/helpers")
    package(root, "src/spec_agent")
    assert runners.python_layout(root) == ("src", "spec_agent")  # the project's own name wins over the first
    hint = runners.import_hint(root, "pytest")
    assert hint is not None and "`from spec_agent import ...`" in hint and "never `src.spec_agent`" in hint
    assert "installed in its virtualenv" in hint and "from src.queue" not in hint


def test_src_as_a_package_keeps_the_src_prefix(tmp_path: Path) -> None:
    root = project(tmp_path)
    package(root, "src")
    (root / "src/queue.py").write_text("")
    assert runners.python_layout(root) == ("src-package", None)
    assert "`from src.queue import backoff_delay`" in (runners.import_hint(root, "pytest") or "")


def test_flat_layout_imports_from_the_root(tmp_path: Path) -> None:
    root = project(tmp_path, "billing")
    for rel in ("billing", "tests", "docs", "scripts", "not-a-module"):
        package(root, rel)
    assert runners.python_layout(root) == ("flat", "billing")  # tests/docs/scripts are not the project's package
    hint = runners.import_hint(root, "pytest")
    assert hint is not None and "`from billing import ...`" in hint and "puts the root on sys.path" in hint


def test_nothing_recognisable_gets_the_general_hint(tmp_path: Path) -> None:
    assert runners.python_layout(tmp_path) == ("flat", None)
    assert "or by package name if the project is installed" in (runners.import_hint(tmp_path, "pytest") or "")
    assert "../../src/queue" in (runners.import_hint(tmp_path, "vitest") or "")
    assert runners.import_hint(tmp_path, "cargo") is None


# --- through the MCP tool --------------------------------------------------------------------------


def constraints(files: list[str]) -> dict[str, Any]:
    async def go() -> dict[str, Any]:
        async with Client(mcp) as client:
            result = await client.call_tool("get_constraints", {"files": files})
            return result.structured_content or json.loads(result.content[0].text)

    return anyio.run(go)


@pytest.fixture
def src_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = project(tmp_path / "proj")
    package(root, "src/demo")
    scaffold.init(root, auto_run=True, actor="Maya Rao <maya@example.com>")
    monkeypatch.setenv("SEAMSPEC_ROOT", str(root))
    return root


def test_get_constraints_says_how_to_import_and_where_the_runner_comes_from(
    src_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = src_project / ".venv/bin/pytest"
    tool.parent.mkdir(parents=True)
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)  # an activated environment would win over .venv
    hint = constraints(["src/demo/core.py"])["runners"][0]
    assert hint["runner"] == "pytest" and "`from demo import ...`" in hint["import_hint"]
    assert "`pytest` resolves to .venv/bin/pytest" in hint["command"]
    assert "without activation, so config.toml needs no change" in hint["command"]


def test_a_missing_runner_program_is_said_plainly(src_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(src_project / "no-tools-here"))
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    command = constraints(["src/demo/core.py"])["runners"][0]["command"]
    assert "`pytest` was not found" in command and "install it in the project" in command


def test_init_explains_the_lookup_next_to_the_runner_command(tmp_path: Path) -> None:
    text = scaffold.render_config("enforced", ["pytest", "vitest"])
    assert "# `pytest` is looked up in the project's .venv / venv first, without activating it" in text
    assert "vitest itself comes from the project's node_modules/.bin" in text
