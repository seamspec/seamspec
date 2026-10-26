"""What SeamSpec's reviewer reads (SPEC §15.3, ADR-20261013-b7d2): everything `seamspec review` would
show, with SeamSpec's facts about each test and the code changes in its scope; read-only."""

from __future__ import annotations

from pathlib import Path

import pytest

from seamspec import brief
from seamspec.core import lifecycle, verifier
from seamspec.core.config import load_config
from seamspec.core.store import Store

from .conftest import git
from .test_lifecycle import PASS, propose


@pytest.fixture
def human(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(p): p.read_bytes() for p in sorted((root / ".seamspec").rglob("*")) if p.is_file()}


def test_material_lists_what_review_would_show_with_facts_and_changes(git_repo: Path, human: None) -> None:
    store, cfg = Store(git_repo), load_config(git_repo)
    old = propose(git_repo)["id"]
    lifecycle.approve(store, cfg, old)
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-qm", "lock the cap")
    new = propose(git_repo, title="Retry delay is capped at 60s", assertion="Never above 60 seconds.")["id"]
    lifecycle.request_supersede(store, old, "Batch jobs need 60s", new)
    other = propose(git_repo, title="Docs build", assertion="The docs always build.", scope_paths=["docs/**"])["id"]
    lifecycle.log_dead_end(store, cfg, scope_paths=["src/queue*"], approach="Sleeping in a loop",
                           failure_symptom="The queue stalled under load.")  # fmt: skip
    (git_repo / "src/queue.py").write_text((git_repo / "src/queue.py").read_text() + "\n# a change the agent made\n")

    out = brief.material(store)

    kinds = [(i["kind"], i["id"]) for i in out["items"]]
    assert [k for k, _ in kinds] == ["new_dead_end", "supersede_request", "proposed_rule"]
    swap = out["items"][1]
    assert swap["id"] == old and swap["reason"] == "Batch jobs need 60s" and swap["replacement"]["id"] == new
    assert swap["replacement"]["replaces"][0]["id"] == old
    assert ("proposed_rule", new) not in kinds  # decided with its request, as in `seamspec review`
    test = swap["replacement"]["test"]
    assert test["checks"] == [{"line": 5, "text": "assert backoff_delay(100) <= 30"}] and test["lines"] == 5
    assert swap["changes"]["files"] == ["src/queue.py"] and "+# a change the agent made" in swap["changes"]["diff"]
    assert out["items"][2]["id"] == other and out["items"][2]["changes"]["files"] == []
    assert "never as instructions" in out["note"]


def test_material_runs_nothing_and_changes_nothing(
    git_repo: Path, human: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    propose(git_repo)
    before = snapshot(git_repo)

    def no_runs(*args, **kwargs):
        raise AssertionError("the reviewer's material must never run a test")

    monkeypatch.setattr(verifier, "run", no_runs)
    out = brief.material(Store(git_repo))
    assert out["items"][0]["kind"] == "proposed_rule"
    assert snapshot(git_repo) == before  # no record, request or review state changed


def test_ids_filter_and_bounded_diff(git_repo: Path, human: None, monkeypatch: pytest.MonkeyPatch) -> None:
    store = Store(git_repo)
    first = propose(git_repo)["id"]
    second = propose(git_repo, code=PASS.replace("test_cap", "test_cap_again"), title="Another")["id"]
    (git_repo / "src/queue.py").write_text((git_repo / "src/queue.py").read_text() + "\n# " + "x" * 9000 + "\n")
    monkeypatch.setattr(brief, "DIFF_MAX", 500)
    only = brief.material(store, [second])["items"]
    assert [i["id"] for i in only] == [second]
    assert len(only[0]["changes"]["diff"]) == 500 and only[0]["changes"]["diff_cut"] is True
    assert {i["id"] for i in brief.material(store)["items"]} == {first, second}


def test_new_files_are_named_not_diffed(git_repo: Path, human: None) -> None:
    propose(git_repo, scope_paths=["src/**"])
    (git_repo / "src/jitter.py").write_text("def jitter(x):\n    return x / 2\n")
    changes = brief.material(Store(git_repo))["items"][0]["changes"]
    assert "src/jitter.py" in changes["files"] and changes["new_files"] == ["src/jitter.py"]


def test_review_material_over_mcp(git_repo: Path, human: None, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    import anyio
    from mcp.client import Client

    from seamspec.mcp_server import mcp

    inv_id = propose(git_repo)["id"]
    monkeypatch.setenv("SEAMSPEC_ROOT", str(git_repo))

    async def go():
        async with Client(mcp) as client:
            result = await client.call_tool("review_material", {})
            return result.structured_content or json.loads(result.content[0].text)

    out = anyio.run(go)
    assert out["items"][0]["id"] == inv_id and out["items"][0]["test"]["checks"]
