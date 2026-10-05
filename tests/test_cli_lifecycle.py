"""CLI lifecycle commands (SPEC §15): agent JSON paths and human-only paths."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from seamspec.cli import app
from seamspec.core.models import InvStatus
from seamspec.core.store import Store

from .test_lifecycle import PASS

runner = CliRunner()


@pytest.fixture
def in_repo(py_repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(py_repo)
    return py_repo


PROPOSAL = {
    "title": "Retry delay is capped",
    "assertion": "Retry delay never exceeds 30 seconds.",
    "scope_paths": ["src/queue*"],
    "runner": "pytest",
    "harness_code": PASS,
    "origin_text": "never more than 30s",
}


def cli_propose(**extra) -> dict:
    result = runner.invoke(app, ["propose", "--json", "-"], input=json.dumps({**PROPOSAL, **extra}))
    return json.loads(result.output)


def test_propose_via_stdin(in_repo: Path) -> None:
    out = cli_propose(adr={"context": "c", "decision": "d", "consequences": []})
    assert out["status"] == "PROPOSED" and out["adr_id"].startswith("ADR-")
    assert Store(in_repo).get(out["id"]).status == InvStatus.PROPOSED


def test_propose_input_errors(in_repo: Path) -> None:
    bad = runner.invoke(app, ["propose", "--json", "-"], input="{not json")
    assert bad.exit_code == 1 and "valid JSON" in bad.output
    unknown = runner.invoke(app, ["propose", "--json", "-"], input=json.dumps({**PROPOSAL, "status": "LOCKED"}))
    assert unknown.exit_code == 1 and "unknown fields: status" in unknown.output
    missing = runner.invoke(app, ["propose", "--json", "-"], input=json.dumps({"title": "x"}))
    assert missing.exit_code == 1 and "missing fields" in missing.output
    wrong = runner.invoke(app, ["propose", "--json", "-"], input=json.dumps({**PROPOSAL, "runner": "jest"}))
    assert wrong.exit_code == 1 and json.loads(wrong.output)["error"] == "invalid"


def test_dead_end_via_stdin(in_repo: Path) -> None:
    payload = {"scope_paths": ["src/**"], "approach": "global retry counter", "failure_symptom": "thundering herd"}
    out = json.loads(runner.invoke(app, ["dead-end", "--json", "-"], input=json.dumps(payload)).output)
    assert out["status"] == "ACTIVE" and Store(in_repo).get(out["id"]).source == "agent"


def test_human_commands_refuse_without_a_terminal(in_repo: Path) -> None:
    inv_id = cli_propose()["id"]
    for args in (["approve", inv_id], ["reject", inv_id, "--reason", "x"], ["supersede", inv_id, "--reason", "x"]):
        result = runner.invoke(app, args, input="y\n")
        assert result.exit_code == 1 and "interactive terminal" in result.output, args
    assert Store(in_repo).get(inv_id).status == InvStatus.PROPOSED


def test_approve_shows_the_test_and_needs_a_yes(in_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")
    inv_id = cli_propose()["id"]
    declined = runner.invoke(app, ["approve", inv_id], input="n\n")
    assert declined.exit_code == 1 and "| def test_cap():" in declined.output
    assert Store(in_repo).get(inv_id).status == InvStatus.PROPOSED
    accepted = runner.invoke(app, ["approve", inv_id], input="y\n")
    assert accepted.exit_code == 0, accepted.output
    assert f"LOCKED {inv_id}" in accepted.output
    assert Store(in_repo).get(inv_id).status == InvStatus.LOCKED


def test_reject_with_dead_end(in_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")
    inv_id = cli_propose()["id"]
    out = runner.invoke(app, ["reject", inv_id, "--reason", "wrong layer", "--dead-end"])
    assert out.exit_code == 0 and "dead end de_" in out.output


def test_supersede_request_then_human_approval(in_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")
    inv_id = cli_propose()["id"]
    runner.invoke(app, ["approve", inv_id], input="y\n")
    monkeypatch.delenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE")

    req = runner.invoke(app, ["supersede", inv_id, "--request", "--reason", "now 60s"])  # agent: no TTY needed
    assert json.loads(req.output)["status"] == "pending"
    status = json.loads(runner.invoke(app, ["status", "--json"]).output)
    assert status["supersede_requests"] == [inv_id] and status["awaiting_review"] == 1

    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")
    done = runner.invoke(app, ["supersede", inv_id], input="y\n")
    assert done.exit_code == 0 and "pending request: now 60s" in done.output
    assert Store(in_repo).get(inv_id).status == InvStatus.SUPERSEDED


def test_retire_dead_end(in_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"scope_paths": ["src/**"], "approach": "global retry counter", "failure_symptom": "herd"}
    de_id = json.loads(runner.invoke(app, ["dead-end", "--json", "-"], input=json.dumps(payload)).output)["id"]
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")
    out = runner.invoke(app, ["retire-dead-end", de_id, "--reason", "fixed in redis-py 6.2"])
    assert out.exit_code == 0 and Store(in_repo).get(de_id).status == "RETIRED"
