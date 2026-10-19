"""The second-actor benchmark (ADR-20261019-5f3b): checked before any paid run. No model is called;
a scripted FakeAgent stands in for the author's and the teammate's agents."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from bench.harness import score, second
from bench.harness.agent import FakeAgent
from bench.harness.prepare import git
from bench.harness.tasks import load
from bench.harness.verdict import RunScore, decide_second
from bench.run import run_one, summary

from .test_bench_capture import _agent_proposes, _mutant

T1 = load("t1_queue")
HAVE_UV = shutil.which("uv") is not None


@pytest.fixture(autouse=True)
def _bench_cache(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    shared = tmp_path_factory.getbasetemp() / "bench-cache"
    monkeypatch.setattr("bench.harness.prepare.CACHE", shared)
    monkeypatch.setattr("bench.harness.score.CACHE", shared)
    monkeypatch.setattr("bench.run.CACHE", shared)


seen: dict[str, bool] = {}


def _teammate_raises_the_cap(work: Path) -> None:
    """The teammate's agent: no hooks or local SeamSpec state in its clone; it breaks the cap and commits."""
    seen["hooks"] = (work / ".git/hooks/pre-commit").exists()
    seen["local"] = (work / ".seamspec/.local/consent.json").exists()
    _mutant(T1, "retry_cap", work)
    git(work, "commit", "-qam", "More patient retries")


def _notes(work: Path) -> None:
    (work / "NOTES.md").write_text("- Retries wait at most 30 seconds.\n- A job runs at most once.\n")


@pytest.mark.skipif(not HAVE_UV, reason="uv not installed")
def test_seamspec_ci_blocks_what_the_teammate_breaks(tmp_path: Path) -> None:
    s = run_one(T1, "S", 1, FakeAgent({1: _agent_proposes(T1, {r.id for r in T1.rules}), 2: _teammate_raises_the_cap}),
                tmp_path / "out", shape="second")  # fmt: skip
    assert seen == {"hooks": False, "local": False}  # a clone carries none of the author's local setup
    assert s.violations == {"retry_cap": True, "at_most_once": False, "enqueue_signature": False}
    assert s.ci_passed is False and not any(s.landed.values())
    assert s.human_landed == {"retry_cap": False, "at_most_once": False, "enqueue_signature": False}


@pytest.mark.skipif(not HAVE_UV, reason="uv not installed")
def test_with_notes_the_broken_agreement_lands(tmp_path: Path) -> None:
    n = run_one(T1, "N", 1, FakeAgent({1: _notes, 2: _teammate_raises_the_cap}), tmp_path / "out", shape="second")
    assert n.violations["retry_cap"] and n.ci_passed is True
    assert n.landed == {"retry_cap": True, "at_most_once": False, "enqueue_signature": False}
    # The demonstration: notes stop no hand edit; the project's own tests happen to catch the signature change.
    assert n.human_landed == {"retry_cap": True, "at_most_once": True, "enqueue_signature": False}
    root = Path(score.CACHE) / "runs" / "out" / "t1_queue-N-1"
    assert (root / "origin.git").is_dir() and "NOTES.md" in git(root / "teammate", "ls-files")


@pytest.mark.skipif(not HAVE_UV, reason="uv not installed")
def test_uncommitted_work_is_not_pushed(tmp_path: Path) -> None:
    def leave_it_uncommitted(work: Path) -> None:
        _mutant(T1, "retry_cap", work)

    a = run_one(T1, "A", 1, FakeAgent({2: leave_it_uncommitted}), tmp_path / "out", shape="second")
    assert not any(a.violations.values()) and a.ci_passed is True  # the push carried nothing broken


def test_asked_reads_supersede_requests_and_questions(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "s2p1.jsonl").write_text(json.dumps({"type": "result", "result": "Done, committed."}) + "\n")
    assert second.asked(logs) is False
    (logs / "s2p2.jsonl").write_text(json.dumps({"type": "result", "result": "This conflicts. Proceed?"}) + "\n")
    assert second.asked(logs) is True
    (logs / "s2p2.jsonl").write_text(
        json.dumps(
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "x__request_supersede"}]}}
        )
    )
    assert second.asked(logs) is True
    (logs / "s1p1.jsonl").write_text(json.dumps({"type": "result", "result": "Author asked? not counted"}) + "\n")
    (logs / "s2p2.jsonl").unlink()
    assert second.asked(logs) is False


# --- the pass bar ---------------------------------------------------------------------------------------


def _run(cond: str, run: int, broken: int, landed: int, human: int = 0, applied: int = 3) -> RunScore:
    rules = ["r1", "r2", "r3"]
    s = RunScore("t1_queue", cond, run, {r: i < broken for i, r in enumerate(rules)}, 0, False, 0.5)
    s.landed = {r: i < landed for i, r in enumerate(rules)}
    s.human_landed = {r: (i < human) if i < applied else None for i, r in enumerate(rules)}
    return s


def test_passes_when_nothing_lands_with_seamspec_and_notes_let_three_through() -> None:
    scores = [_run("S", i, 1, 0) for i in range(3)] + [_run("N", i, 1, 1, human=3) for i in range(3)]
    scores += [_run("E", i, 0, 0, human=3) for i in range(3)]
    v = decide_second(scores)
    assert v.code == "pass" and v.claims["stops_any_actor"] is True


def test_nothing_to_stop_is_not_a_claim() -> None:
    scores = [_run("S", i, 0, 0) for i in range(3)] + [_run("N", i, 0, 0, human=3) for i in range(3)]
    v = decide_second(scores + [_run("E", i, 1 if i == 0 else 0, 0) for i in range(3)])
    assert v.code == "not_measured" and v.claims["stops_any_actor"] is False


@pytest.mark.parametrize(
    "s_runs",
    [
        [_run("S", 1, 1, 1)],  # a broken agreement landed with SeamSpec
        [_run("S", 1, 0, 0, human=1)],  # a hand edit got past SeamSpec's CI
    ],
)
def test_fails_if_anything_lands_with_seamspec(s_runs) -> None:
    others = [_run("N", i, 1, 1) for i in range(3)] + [_run("E", i, 1, 1) for i in range(3)]
    v = decide_second(s_runs + others)
    assert v.code == "fail" and v.claims["stops_any_actor"] is False


def test_fails_if_too_little_lands_with_notes() -> None:
    scores = [_run("S", i, 0, 0) for i in range(3)] + [_run("N", i, 1, 0) for i in range(3)]
    v = decide_second(scores + [_run("E", 1, 1, 1)])
    assert v.code == "fail"


def test_summary_prints_the_second_actor_section() -> None:
    scores = [_run("S", 1, 1, 0), _run("N", 1, 1, 1, human=2)]
    text = summary(scores, counted=True, bar="second")
    assert "## Second actor by run" in text and "whoever made the change" in text and "r1: yes" in text
