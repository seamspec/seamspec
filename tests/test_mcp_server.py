"""MCP server through a real MCP client: in-process, and over stdio via `seamspec mcp` (SPEC §14)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client, StdioServerParameters

from seamspec.core import lifecycle
from seamspec.core.config import load_config
from seamspec.core.models import InvStatus
from seamspec.core.store import Store
from seamspec.mcp_server import mcp

from .test_lifecycle import PASS, propose

TOOLS = ["get_constraints", "propose_invariant", "log_dead_end", "request_supersede", "verify"]
TOKEN_BUDGET = 1500  # SPEC §4.3: tool definitions cost context in every session


@pytest.fixture
def project(git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SEAMSPEC_ROOT", str(git_repo))
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")
    return git_repo


def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    async def go() -> dict[str, Any]:
        async with Client(mcp) as client:
            result = await client.call_tool(name, args)
            return result.structured_content or json.loads(result.content[0].text)

    return anyio.run(go)


def read(uri: str) -> str:
    async def go() -> str:
        async with Client(mcp) as client:
            return (await client.read_resource(uri)).contents[0].text

    return anyio.run(go)


def tool_definitions() -> list[dict[str, Any]]:
    async def go():
        async with Client(mcp) as client:
            return [t.model_dump(mode="json", exclude_none=True) for t in (await client.list_tools()).tools]

    return anyio.run(go)


def test_exactly_the_v01_tools_within_the_token_budget() -> None:
    defs = tool_definitions()
    assert [d["name"] for d in defs] == TOOLS
    approx_tokens = len(json.dumps(defs)) / 4
    assert approx_tokens < TOKEN_BUDGET, f"tool definitions ~{approx_tokens:.0f} tokens"


def test_get_constraints(project: Path) -> None:
    from .conftest import make_dead_end

    inv_id = propose(project)["id"]
    lifecycle.approve(Store(project), load_config(project), inv_id)
    Store(project).create(make_dead_end(paths=["src/**"]))
    out = call("get_constraints", {"files": ["src/queue.py"]})
    assert [i["id"] for i in out["locked"]] == [inv_id]
    assert f"[LOCKED] {inv_id}" in out["summary"] and "Previously tried and failed" in out["summary"]
    assert out["runners"] == [{"runner": "pytest", "test_location": ".seamspec/tests/test_<id>.py"}]
    assert call("get_constraints", {"files": ["README.md"]})["summary"].startswith("No SeamSpec rules")


def test_propose_runs_nothing_and_honors_the_queue(project: Path) -> None:
    marker = project.parent / "ran.txt"
    code = f"open({str(marker)!r}, 'w').write('x')\n" + PASS
    args = {"title": "Retry delay is capped", "assertion": "Retry delay never exceeds 30 seconds.",
            "scope_paths": ["src/**"], "runner": "pytest", "harness_code": code, "origin_text": "cap at 30s",
            "adr": {"context": "Retry storms.", "decision": "Cap at 30s.", "consequences": ["Bounded"]}}  # fmt: skip
    out = call("propose_invariant", args)
    assert out["status"] == "PROPOSED" and out["verify"]["run"].startswith("seamspec verify --proposed")
    assert out["adr_id"].startswith("ADR-") and not marker.exists()
    cfg_path = project / ".seamspec/config.toml"
    cfg_path.write_text(cfg_path.read_text().replace("max_pending = 10", "max_pending = 1"))
    assert call("propose_invariant", args)["error"] == "queue_full"


def test_propose_rejects_bad_input(project: Path) -> None:
    bad = {"title": "x", "assertion": "short", "scope_paths": [], "runner": "jest", "harness_code": "x",
           "origin_text": "x"}  # fmt: skip
    out = call("propose_invariant", bad)
    assert out["error"] == "invalid" and "jest" in out["message"]


def test_dead_end_and_supersede_request(project: Path) -> None:
    de = call(
        "log_dead_end", {"scope_paths": ["src/**"], "approach": "global retry counter", "failure_symptom": "herd"}
    )
    assert de["status"] == "ACTIVE"
    inv_id = propose(project)["id"]
    assert call("request_supersede", {"invariant_id": inv_id, "reason": "x"})["error"] == "invalid"  # not LOCKED
    lifecycle.approve(Store(project), load_config(project), inv_id)
    assert call("request_supersede", {"invariant_id": inv_id, "reason": "now 60s"})["status"] == "pending"
    assert Store(project).get(inv_id).status == InvStatus.LOCKED  # a request changes no record


def test_verify_runs_locked_only_where_permitted(project: Path) -> None:
    inv_id = propose(project)["id"]
    assert call("verify", {})["checked"] == []  # proposals never run
    lifecycle.approve(Store(project), load_config(project), inv_id)
    assert call("verify", {})["passed"] is True
    (project / "src/queue.py").write_text("def backoff_delay(n):\n    return 99\n")
    out = call("verify", {"scope": "changed"})
    assert out["passed"] is False and out["failing_ids"] == [inv_id] and "99" in out["failures"][0]["output"]
    (project / ".seamspec/.local/trust.json").unlink()
    assert call("verify", {})["error"] == "not_permitted"


def test_adr_resources(project: Path) -> None:
    out = propose(project, adr_draft={"context": "c", "decision": "Cap at 30s.", "consequences": []})
    assert out["adr_id"] in read("seamspec://adrs")
    assert "## Decision\nCap at 30s." in read(f"seamspec://adrs/{out['adr_id']}")
    assert read("seamspec://adrs/ADR-20990101-ffff") == "No decision record ADR-20990101-ffff."


def test_not_a_seamspec_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert call("get_constraints", {"files": ["x.py"]})["error"] == "not_a_seamspec_project"


@pytest.mark.skipif(shutil.which("seamspec") is None, reason="seamspec CLI not on PATH")
def test_seamspec_mcp_over_stdio(project: Path) -> None:
    """`seamspec mcp` is what the plugin launches; talk to it like Claude Code would."""

    async def go():
        params = StdioServerParameters(
            command="seamspec",
            args=["mcp"],
            env={"SEAMSPEC_ROOT": str(project), "PATH": __import__("os").environ["PATH"]},
        )  # noqa: E501
        async with Client(params) as client:
            names = [t.name for t in (await client.list_tools()).tools]
            result = await client.call_tool("get_constraints", {"files": ["src/queue.py"]})
            return names, result

    names, result = anyio.run(go)
    assert names == TOOLS and not result.is_error
