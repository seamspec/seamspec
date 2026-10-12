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

TOOLS = ["get_constraints", "propose_invariant", "log_dead_end", "request_supersede", "verify", "open_review"]
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
    assert out["runners"][0]["runner"] == "pytest"
    assert out["runners"][0]["test_location"] == ".seamspec/tests/test_<id>.py"
    assert "from src.queue import" in out["runners"][0]["import_hint"]
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


# --- a session moved to another folder (dogfooding finding #2, ADR-20261011-d4a1) ------------------


def call_from(roots: list[Path] | None, name: str, args: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Call a tool from a client whose session has these folders open. Also: how often it was asked for them."""
    from mcp_types import ListRootsResult, Root

    asked = 0

    async def list_roots(context: Any) -> ListRootsResult:
        nonlocal asked
        asked += 1
        return ListRootsResult(roots=[Root(uri=p.resolve().as_uri()) for p in roots or []])

    async def go() -> dict[str, Any]:
        async with Client(mcp, list_roots_callback=list_roots if roots is not None else None) as client:
            result = await client.call_tool(name, args)
            return result.structured_content or json.loads(result.content[0].text)

    return anyio.run(go), asked


@pytest.fixture
def moved(git_repo: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The server was started for a launch folder that isn't a SeamSpec project; the session then
    moved to `git_repo`. The plugin's SEAMSPEC_ROOT still names the launch folder."""
    launch = tmp_path_factory.mktemp("scratch-launch-folder")
    monkeypatch.setenv("SEAMSPEC_ROOT", str(launch))
    monkeypatch.chdir(launch)
    return git_repo


def test_tools_find_the_project_among_the_sessions_folders(moved: Path) -> None:
    launch = Path.cwd()
    out, asked = call_from([launch, moved], "get_constraints", {"files": ["src/queue.py"]})
    assert "error" not in out and out["files"] == ["src/queue.py"] and asked == 1
    dead_end = {"scope_paths": ["src/**"], "approach": "A global retry counter", "failure_symptom": "It starved jobs"}
    out, _ = call_from([launch, moved], "log_dead_end", dead_end)
    assert out["status"] == "ACTIVE" and (moved / ".seamspec/dead_ends" / f"{out['id']}.json").is_file()
    out, _ = call_from([launch, moved / "src"], "verify", {"scope": "all"})  # a subfolder of the project counts
    assert "error" not in out or out["error"] == "not_permitted"


def test_the_usual_session_is_not_asked_for_its_folders(project: Path) -> None:
    """No extra round trip when the launch folder is the project."""
    out, asked = call_from([project], "get_constraints", {"files": ["src/queue.py"]})
    assert "error" not in out and asked == 0


def test_the_servers_own_folder_counts(moved: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(moved / "src")  # started inside the project, though SEAMSPEC_ROOT names the launch folder
    out, asked = call_from([], "get_constraints", {"files": ["src/queue.py"]})
    assert "error" not in out and asked == 0


def test_an_absolute_file_path_points_to_the_project(moved: Path) -> None:
    out, _ = call_from(None, "get_constraints", {"files": [str(moved / "src/queue.py")]})
    assert "error" not in out and out["files"] == ["src/queue.py"]


def test_no_project_anywhere_says_which_folder_was_tried(moved: Path) -> None:
    launch = Path.cwd()
    for roots in (None, [launch]):  # a client without roots, and roots that don't help
        out, _ = call_from(roots, "get_constraints", {"files": ["x.py"]})
        assert out["error"] == "not_a_seamspec_project"
        assert str(launch) in out["message"] and "Start a new session in your project folder" in out["message"]


def test_two_projects_in_one_session_is_not_guessed(moved: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    from seamspec.installers import scaffold

    other = tmp_path_factory.mktemp("other-project")
    (other / "pyproject.toml").write_text('[project]\nname = "other"\n')
    scaffold.init(other, auto_run=True, actor="Maya Rao <maya@example.com>")
    out, _ = call_from([moved, other], "get_constraints", {"files": ["x.py"]})
    assert out["error"] == "not_a_seamspec_project" and "2 SeamSpec projects" in out["message"]
    assert str(moved) in out["message"] and str(other.resolve()) in out["message"]


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


def test_get_constraints_includes_decisions(project: Path) -> None:
    """Copilot on #17: ADR summaries for the files (§14.1): linked from a rule, or scoped to the files."""
    from seamspec.core import adr as adr_mod

    linked = propose(project, adr_draft={"context": "c", "decision": "Cap at 30s.", "consequences": []})["adr_id"]
    scoped = adr_mod.create(Store(project), "Queue uses Redis", "c", "d", [], scopes=["src/queue*"]).id
    elsewhere = adr_mod.create(Store(project), "Auth uses JWT", "c", "d", [], scopes=["src/auth/**"]).id
    ids = {a["id"] for a in call("get_constraints", {"files": ["src/queue.py"]})["adrs"]}
    assert linked in ids and scoped in ids and elsewhere not in ids
