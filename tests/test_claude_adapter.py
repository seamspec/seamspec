"""Claude Code hook adapter with recorded-shape payloads (SPEC §7.2, §16.1).

Payload fields follow the Claude Code hooks reference (checked 2026-10-05): PreToolUse has
session_id, prompt_id, cwd, hook_event_name, tool_name, tool_input; Stop has session_id, prompt_id,
cwd, stop_reason, last_assistant_message (no stop_hook_active any more).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from seamspec.adapters import claude
from seamspec.core import lifecycle
from seamspec.core.config import load_config
from seamspec.core.store import Store

from .conftest import make_dead_end
from .test_lifecycle import PASS, propose

BROKEN_CODE = "def backoff_delay(n):\n    return 0.1 * 2 ** n\n"


@pytest.fixture
def human(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")


def pre(root: Path, file: str, tool: str = "Edit", session: str = "s1", **extra) -> dict | None:
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    payload = {
        "session_id": session,
        "prompt_id": "p1",
        "cwd": str(root),
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": {key: file},
        **extra,
    }
    out = claude.main("pre-tool-use", json.dumps(payload))
    return json.loads(out) if out else None


def stop(root: Path, prompt: str = "p1", session: str = "s1", **extra) -> dict | None:
    payload = {"session_id": session, "prompt_id": prompt, "cwd": str(root), "hook_event_name": "Stop",
               "stop_reason": "end_turn", "last_assistant_message": "Done.", **extra}  # fmt: skip
    out = claude.main("stop", json.dumps(payload))
    return json.loads(out) if out else None


def lock(root: Path, code: str = PASS) -> str:
    inv_id = propose(root, code=code)["id"]  # scope: src/queue*
    lifecycle.approve(Store(root), load_config(root), inv_id)
    return inv_id


def set_config(root: Path, old: str, new: str) -> None:
    p = root / ".seamspec/config.toml"
    text = p.read_text()
    assert old in text, old
    p.write_text(text.replace(old, new))


# --- PreToolUse: ledger protection -----------------------------------------------------------------


@pytest.mark.parametrize(
    "rel",
    [
        ".seamspec/invariants/inv_1a2b3c4d.json",
        ".seamspec/tests/test_inv_1a2b3c4d.py",
        ".seamspec/pytest.ini",
        ".seamspec/.local/journal.jsonl",
        ".seamspec/config.toml",
    ],  # fmt: skip
)
def test_protected_paths_are_denied(git_repo: Path, rel: str) -> None:
    out = pre(git_repo, str(git_repo / rel))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "direct edits to SeamSpec records" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_protection_holds_with_gate_off(git_repo: Path) -> None:
    set_config(git_repo, 'gate_mode = "context"', 'gate_mode = "off"')
    assert pre(git_repo, ".seamspec/pytest.ini")["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_ignored_cases(git_repo: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    assert pre(git_repo, str(git_repo.parent / "outside.py")) is None
    assert pre(git_repo, str(git_repo / "src/queue.py"), tool="Bash") is None
    elsewhere = tmp_path_factory.mktemp("not-seamspec")
    assert pre(elsewhere, str(elsewhere / "x.py")) is None


# --- PreToolUse: edit-time context ---------------------------------------------------------------------


def test_context_once_per_file_and_ledger_version(git_repo: Path, human: None) -> None:
    inv_id = lock(git_repo)
    Store(git_repo).create(make_dead_end(paths=["src/**"]))
    out = pre(git_repo, str(git_repo / "src/queue.py"))
    hso = out["hookSpecificOutput"]
    assert "permissionDecision" not in hso, "context must not approve or deny"
    assert f"[LOCKED] {inv_id}" in hso["additionalContext"]
    assert "Previously tried and failed:" in hso["additionalContext"]
    assert pre(git_repo, str(git_repo / "src/queue.py")) is None  # shown once per session
    assert pre(git_repo, str(git_repo / "src/queue.py"), session="s2") is not None  # new session
    Store(git_repo).create(make_dead_end("de_00000002", paths=["src/**"]))  # ledger changed
    assert pre(git_repo, str(git_repo / "src/queue.py")) is not None


def test_relative_paths_and_notebooks(git_repo: Path, human: None) -> None:
    lock(git_repo)
    assert pre(git_repo, "src/queue.py") is not None
    (git_repo / "src/queue_nb.ipynb").write_text("{}")
    assert pre(git_repo, str(git_repo / "src/queue_nb.ipynb"), tool="NotebookEdit") is not None


def test_ungoverned_file_is_silent(git_repo: Path, human: None) -> None:
    lock(git_repo)
    assert pre(git_repo, str(git_repo / "README.md")) is None


def test_brand_new_governed_file_is_denied_once(git_repo: Path, human: None) -> None:
    lock(git_repo)
    target = str(git_repo / "src/queue_v2.py")
    first = pre(git_repo, target, tool="Write")
    assert first["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "Re-attempt the edit" in first["hookSpecificOutput"]["permissionDecisionReason"]
    assert pre(git_repo, target, tool="Write") is None


def test_deny_once_mode(git_repo: Path, human: None) -> None:
    lock(git_repo)
    set_config(git_repo, 'gate_mode = "context"', 'gate_mode = "deny_once"')
    assert pre(git_repo, str(git_repo / "src/queue.py"))["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_advisory_mode_is_silent(git_repo: Path, human: None) -> None:
    lock(git_repo)
    set_config(git_repo, 'mode = "enforced"', 'mode = "advisory"')
    assert pre(git_repo, str(git_repo / "src/queue.py")) is None
    assert pre(git_repo, ".seamspec/pytest.ini") is None


# --- Stop gate -----------------------------------------------------------------------------------------


def test_green_stop_is_silent_and_cached(git_repo: Path, human: None) -> None:
    marker = git_repo.parent / "runs.txt"
    lock(git_repo, code=f"open({str(marker)!r}, 'a').write('x')\n" + PASS)
    marker.unlink(missing_ok=True)
    assert stop(git_repo) is None and marker.read_text() == "x"
    assert stop(git_repo) is None and marker.read_text() == "x", "unchanged tree must not re-run"
    (git_repo / "src/queue.py").write_text((git_repo / "src/queue.py").read_text() + "\n# touched\n")
    assert stop(git_repo) is None and marker.read_text() == "xx"


def test_regression_blocks_with_retry_cap_per_prompt(git_repo: Path, human: None) -> None:
    inv_id = lock(git_repo)
    (git_repo / "src/queue.py").write_text(BROKEN_CODE)
    for attempt in (1, 2, 3):
        out = stop(git_repo)
        assert out["decision"] == "block", out
        assert f"[FAIL] {inv_id} (pytest)" in out["reason"] and f"Attempt {attempt} of 3" in out["reason"]
        assert "request_supersede" in out["reason"]
    capped = stop(git_repo)
    assert "decision" not in capped and "still failing after 3 attempts" in capped["systemMessage"]
    assert stop(git_repo, prompt="p2")["decision"] == "block"  # a new user prompt gets a fresh budget


def test_legacy_stop_hook_active(git_repo: Path, human: None) -> None:
    lock(git_repo)
    (git_repo / "src/queue.py").write_text(BROKEN_CODE)
    payload = {"session_id": "old", "cwd": str(git_repo), "stop_hook_active": False}
    for _ in range(3):
        assert json.loads(claude.main("stop", json.dumps({**payload, "stop_hook_active": True})))["decision"] == "block"
    assert "systemMessage" in json.loads(claude.main("stop", json.dumps({**payload, "stop_hook_active": True})))
    assert json.loads(claude.main("stop", json.dumps(payload)))["decision"] == "block"  # fresh stop resets


def test_pending_supersede_lets_the_agent_stop(git_repo: Path, human: None) -> None:
    inv_id = lock(git_repo)
    (git_repo / "src/queue.py").write_text(BROKEN_CODE)
    lifecycle.request_supersede(Store(git_repo), inv_id, "cap is changing")
    out = stop(git_repo)
    assert "decision" not in out and "supersede requested" in out["systemMessage"]


def test_silent_retirement_blocks(git_repo: Path, human: None) -> None:
    from .conftest import git

    inv_id = lock(git_repo)
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-q", "-m", "lock")
    (Store(git_repo).local / "journal.jsonl").unlink()
    store = Store(git_repo)
    store.save(store.get(inv_id).model_copy(update={"status": lifecycle.InvStatus.SUPERSEDED, "status_reason": "x"}))
    out = stop(git_repo)
    assert out["decision"] == "block" and "outside the SeamSpec CLI" in out["reason"]


def test_untrusted_or_advisory_runs_nothing(git_repo: Path, human: None) -> None:
    marker = git_repo.parent / "ran.txt"
    lock(git_repo, code=f"open({str(marker)!r}, 'a').write('x')\n" + PASS)
    marker.unlink(missing_ok=True)
    (git_repo / ".seamspec/.local/trust.json").unlink()
    out = stop(git_repo)
    assert "not checked" in out["systemMessage"] and not marker.exists()
    set_config(git_repo, 'mode = "enforced"', 'mode = "advisory"')
    assert stop(git_repo) is None and not marker.exists()


def test_deadline_is_incomplete_not_silent(git_repo: Path, human: None) -> None:
    hang = "import time\n\n\ndef test_slow():\n    time.sleep(30)\n"
    lock(git_repo, code=PASS)
    inv_slow = propose(git_repo, code=hang)["id"]
    store, cfg = Store(git_repo), load_config(git_repo)
    fast = cfg.model_copy(update={"verify": cfg.verify.model_copy(update={"timeout_seconds": 60})})
    # approve the slow rule without running it for 30s: lock it by hand, journaled like the CLI does
    import shutil

    inv = store.get(inv_slow)
    final = cfg.runners["pytest"].harness_path(inv.id)
    shutil.move(str(git_repo / inv.verification.harness_path), str(git_repo / final))
    from seamspec.core import journal
    from seamspec.core.hashing import sha256_file, sha256_text
    from seamspec.core.models import utcnow

    verification = inv.verification.model_copy(
        update={
            "harness_path": final,
            "harness_sha256": sha256_file(git_repo / final),
            "assertion_sha256": sha256_text(inv.assertion),
        }
    )
    locked = {"status": lifecycle.InvStatus.LOCKED, "approved_at": utcnow(), "approved_by": "t"}
    store.save(inv.model_copy(update={**locked, "verification": verification}))
    journal.append(store, inv.id, "PROPOSED", "LOCKED", "t")
    short = fast.model_copy(update={"verify": fast.verify.model_copy(update={"stop_deadline_seconds": 2})})
    payload = {"session_id": "s1", "prompt_id": "p1", "cwd": str(git_repo)}
    out = claude.stop(payload, store, short)
    assert "decision" not in out and "time ran out" in out["systemMessage"]
    strict = short.model_copy(update={"hooks": short.hooks.model_copy(update={"fail_closed": True})})
    out = claude.stop(payload, store, strict)
    assert out["decision"] == "block" and "[INCOMPLETE]" in out["reason"]


# --- errors ---------------------------------------------------------------------------------------------


def test_errors_fail_open_by_default(git_repo: Path) -> None:
    (git_repo / ".seamspec/invariants/inv_deadbeef.json").write_text("{not json")
    assert pre(git_repo, str(git_repo / "src/queue.py")) is None
    out = stop(git_repo)
    assert "decision" not in out and "SeamSpec hook error" in out["systemMessage"]
    assert claude.main("pre-tool-use", "not json") == ""


def test_fail_closed_errors_are_retry_capped(git_repo: Path) -> None:
    set_config(git_repo, "fail_closed = false", "fail_closed = true")
    (git_repo / ".seamspec/invariants/inv_deadbeef.json").write_text("{not json")
    for _ in range(3):
        assert stop(git_repo)["decision"] == "block"
    assert "still failing after 3 attempts" in stop(git_repo)["systemMessage"]


def test_cli_entry_point_prints_block_and_exits_zero(git_repo: Path, human: None) -> None:
    """Decisions travel in the JSON; the exit code is 0 even when the hook blocks."""
    from typer.testing import CliRunner

    from seamspec.cli import app

    inv_id = lock(git_repo)
    (git_repo / "src/queue.py").write_text(BROKEN_CODE)
    payload = json.dumps({"session_id": "s", "prompt_id": "p", "cwd": str(git_repo)})
    result = CliRunner().invoke(app, ["hook", "claude", "stop"], input=payload)
    assert result.exit_code == 0
    out = json.loads(result.output)
    assert out["decision"] == "block" and inv_id in out["reason"]
