"""The capture and long-session benchmarks (ADR-20261015-c8e1): checked before any paid run. No model
is called; a scripted FakeAgent stands in for Claude Code."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from bench.harness import capture, score
from bench.harness.agent import FakeAgent
from bench.harness.prepare import SELF_NOTES, prepare
from bench.harness.tasks import TASK_IDS, load
from bench.harness.verdict import RunScore, decide_capture, decide_long
from bench.run import run_one, summary

T1, T2, T3 = load("t1_queue"), load("t2_prices"), load("t3_export")
HAVE_UV = shutil.which("uv") is not None
HAVE_NPM = shutil.which("npm") is not None


@pytest.fixture(autouse=True)
def _bench_cache(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    shared = tmp_path_factory.getbasetemp() / "bench-cache"
    monkeypatch.setattr("bench.harness.prepare.CACHE", shared)
    monkeypatch.setattr("bench.harness.score.CACHE", shared)
    monkeypatch.setattr("bench.run.CACHE", shared)


# --- task data ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_every_rule_has_a_mutant_and_the_long_session_is_fixed(task_id: str) -> None:
    task = load(task_id)
    assert task.capture is not None and set(task.capture.mutants) == {r.id for r in task.rules}
    assert len(task.fillers) == 12
    long = task.long_session()
    assert long[: len(task.sessions[0])] == task.sessions[0] and long[-len(task.sessions[2]) :] == task.sessions[2]
    assert len(long) == sum(len(s) for s in task.sessions) + 12


def test_unrelated_requests_never_restate_or_hint_at_the_rules() -> None:
    giveaways = ("30 seconds", "at most once", "half-even", "banker", "negative", "deadlock", "standard error",
                 "exit code", "position", "eval", "security", "round", "retr", "thread", "parallel",
                 "stdout")  # fmt: skip
    for task in (T1, T2, T3):
        text = " ".join(task.fillers).lower()
        assert not [g for g in giveaways if g in text], task.id


def _mutant(task, rule_id: str, work: Path) -> None:
    for edit in task.capture.mutants[rule_id]:
        path = work / edit.file
        path.write_text(path.read_text().replace(edit.old, edit.new, 1))


@pytest.mark.skipif(not HAVE_UV, reason="uv not installed")
@pytest.mark.parametrize("task", [T1, T3], ids=lambda t: t.id)
def test_each_python_mutant_breaks_exactly_its_own_agreement(tmp_path: Path, task) -> None:
    for rule in task.rules:
        work = tmp_path / rule.id
        shutil.copytree(task.template, work)
        _mutant(task, rule.id, work)
        assert score.oracle(task, work) == {r.id: r.id != rule.id for r in task.rules}, rule.id


@pytest.mark.skipif(not HAVE_NPM, reason="npm not installed")
def test_each_typescript_mutant_breaks_exactly_its_own_agreement(tmp_path: Path) -> None:
    for rule in T2.rules:
        work = tmp_path / rule.id
        shutil.copytree(T2.template, work)
        _mutant(T2, rule.id, work)
        assert score.oracle(T2, work) == {r.id: r.id != rule.id for r in T2.rules}, rule.id


# --- capture scoring and the scripted person ---------------------------------------------------------


def _agent_proposes(task, rule_ids, extra_code: dict[str, str] | None = None):
    """A scripted session 1 in condition S: the agent proposes the task's rule tests (from rules/) and
    logs the dead end, as SeamSpec's protocol asks."""

    def session(work: Path) -> None:
        from seamspec.core import lifecycle
        from seamspec.core.config import load_config
        from seamspec.core.store import Store

        store, cfg = Store(work), load_config(work)
        for rule in task.rules:
            if rule.id in rule_ids:
                lifecycle.propose_invariant(store, cfg, title=rule.title, assertion=rule.assertion,
                                            scope_paths=list(rule.scope), runner=task.runner,
                                            harness_code=task.rule_source(rule, "rules", 2),
                                            origin_text="Said in session 1.")  # fmt: skip
        for title, code in (extra_code or {}).items():
            lifecycle.propose_invariant(store, cfg, title=title, assertion=title, scope_paths=["src/**"],
                                        runner=task.runner, harness_code=code, origin_text="Session 1.")  # fmt: skip
        lifecycle.log_dead_end(store, cfg, scope_paths=list(task.dead_end.scope), approach=task.dead_end.approach,
                               failure_symptom=task.dead_end.symptom)  # fmt: skip

    return session


@pytest.mark.skipif(not HAVE_UV, reason="uv not installed")
def test_condition_s_captures_only_what_a_locked_test_really_protects(tmp_path: Path) -> None:
    """Two of three rules proposed, plus a rule about new code (fails on the starting code, so it can't
    count) and one whose test fails (the reviewer rejects it). Then session 2 breaks the uncaptured rule."""
    new_feature = "import sys\nfrom pathlib import Path\n\nsys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))\n\nfrom jobqueue import Queue  # noqa: E402\n\n\ndef test_pending():\n    q = Queue(sleep=lambda s: None)\n    q.enqueue({})\n    assert q.pending() == 1\n"  # noqa: E501
    failing = "def test_never():\n    assert False\n"

    def add_pending(work: Path) -> None:
        queue = work / "src/jobqueue/queue.py"
        queue.write_text(queue.read_text() + "\n    def pending(self) -> int:\n        return len(self._waiting)\n")
        _agent_proposes(T1, {"retry_cap", "at_most_once"}, {"Pending counts waiting jobs": new_feature,
                                                            "Something impossible": failing})(work)  # fmt: skip

    def break_signature(work: Path) -> None:
        _mutant(T1, "enqueue_signature", work)

    s = run_one(T1, "S", 1, FakeAgent({1: add_pending, 2: break_signature}), tmp_path / "out")
    assert s.captured == {"retry_cap": True, "at_most_once": True, "enqueue_signature": False}
    assert s.captured_dead_end is True and s.captured_share == pytest.approx(3 / 4)
    assert "Something impossible" not in (s.approved or []) and "Pending counts waiting jobs" in (s.approved or [])
    assert s.violations == {"retry_cap": False, "at_most_once": False, "enqueue_signature": True}
    assert s.tampering == 0
    work = Path(score.CACHE) / "runs" / "out" / "t1_queue-S-1"
    from seamspec.core.models import InvStatus
    from seamspec.core.store import Store

    statuses = sorted(i.status.value for i in Store(work).load_all("inv"))
    assert statuses == ["LOCKED", "LOCKED", "LOCKED", "REJECTED"]
    assert (
        "Review: approve SeamSpec rules"
        in __import__("subprocess").run(["git", "log", "--format=%s"], cwd=work, capture_output=True, text=True).stdout
    )
    assert InvStatus.LOCKED  # the scripted person approved through SeamSpec's own lifecycle


@pytest.mark.skipif(not HAVE_UV, reason="uv not installed")
def test_condition_s_with_nothing_proposed_captures_nothing(tmp_path: Path) -> None:
    s = run_one(T1, "S", 1, FakeAgent({}), tmp_path / "out")
    assert s.captured == {r.id: False for r in T1.rules} and s.captured_dead_end is False
    assert s.captured_share == 0 and s.approved == []


@pytest.mark.skipif(not (HAVE_UV and HAVE_NPM), reason="uv or npm not installed")
def test_condition_s_capture_works_for_typescript(tmp_path: Path) -> None:
    """vitest keeps rule tests outside .seamspec/: the capture copy must bring them along."""
    s = run_one(T2, "S", 1, FakeAgent({1: _agent_proposes(T2, {"rounding", "non_negative"})}), tmp_path / "out")
    assert s.captured == {"rounding": True, "non_negative": True} and s.captured_dead_end is True


@pytest.mark.skipif(not HAVE_UV, reason="uv not installed")
def test_the_reviewer_declines_a_supersede_request_and_its_replacement(tmp_path: Path) -> None:
    work = prepare(T1, "S", tmp_path / "w").work
    _agent_proposes(T1, {"retry_cap"})(work)
    capture.review(work)
    from seamspec.core import lifecycle, requests
    from seamspec.core.config import load_config
    from seamspec.core.models import Invariant, InvStatus
    from seamspec.core.store import Store

    store, cfg = Store(work), load_config(work)
    old = next(i for i in store.load_all("inv") if isinstance(i, Invariant) and i.status == InvStatus.LOCKED)
    code = "def test_x():\n    assert True\n"
    longer = "Retries may wait up to ten minutes."
    rep = lifecycle.propose_invariant(store, cfg, title="Retry delay up to 10 minutes", assertion=longer,
                                      scope_paths=["src/**"], runner="pytest", harness_code=code,
                                      origin_text="s2")["id"]  # fmt: skip
    lifecycle.request_supersede(store, old.id, "longer outages", rep)
    done = capture.review(work)
    assert done.declined_requests == 1 and done.rejected == ["Retry delay up to 10 minutes"] and done.approved == []
    assert store.get(old.id).status == InvStatus.LOCKED and not requests.load_all(store)


@pytest.mark.skipif(not HAVE_UV, reason="uv not installed")
def test_condition_n_writes_one_line_and_its_notes_are_read(tmp_path: Path) -> None:
    def notes(work: Path) -> None:
        (work / "NOTES.md").write_text("- Retries wait 30s at most.\n- A job runs only once.\n- Threads deadlocked.\n")

    s = run_one(T1, "N", 1, FakeAgent({1: notes}), tmp_path / "out")
    work = Path(score.CACHE) / "runs" / "out" / "t1_queue-N-1"
    assert (work / "CLAUDE.md").read_text() == SELF_NOTES and not (work / ".seamspec").exists()
    assert s.notes == {"retry_cap": True, "at_most_once": True, "enqueue_signature": False}
    assert s.captured is None and s.gate_catches is None


# --- the long session --------------------------------------------------------------------------------


@pytest.mark.skipif(not HAVE_UV, reason="uv not installed")
def test_long_shape_runs_one_session_and_counts_seamspecs_own_catches(tmp_path: Path) -> None:
    """Claude Code's logs don't show Stop hooks (calibration, 2026-10-18): catches come from SeamSpec's record."""
    seen = []

    class Recorder(FakeAgent):
        def run_session(self, work, session, prompts, use_plugin, log_dir):
            from seamspec.core import catches
            from seamspec.core.store import Store

            seen.append((session, len(prompts), use_plugin))
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / "s1p1.jsonl").write_text(json.dumps({"type": "system", "subtype": "compact_boundary"}) + "\n")
            catches.record(Store(work), "stop", ["inv_00000001"])
            catches.record(Store(work), "commit", ["inv_00000001"])
            return super().run_session(work, session, prompts, use_plugin, log_dir)

    s = run_one(T1, "C", 1, Recorder({}), tmp_path / "out", shape="long")
    assert seen == [(1, len(T1.long_session()), True)]
    assert s.gate_catches == 2 and s.compacted is True
    a = run_one(T1, "A", 1, FakeAgent({}), tmp_path / "out", shape="long")
    assert a.gate_catches == 0 and a.compacted is False


def test_each_prompt_costs_only_its_own_increase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Claude Code reports a session's running total; summing them overstated full-1 ($111.94, really $45.37)."""
    import subprocess as sp

    from bench.harness import agent as agent_mod
    from bench.harness.agent import ClaudeAgent

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    totals = iter([0.09, 0.096, 0.107])

    def fake_run(cmd, **kw):
        stream = [json.dumps({"type": "system", "subtype": "init", "apiKeySource": "ANTHROPIC_API_KEY"}),
                  json.dumps({"type": "result", "is_error": False, "total_cost_usd": next(totals), "num_turns": 2,
                              "session_id": "s"})]  # fmt: skip
        return sp.CompletedProcess(cmd, 0, stdout="\n".join(stream), stderr="")

    monkeypatch.setattr(agent_mod.subprocess, "run", fake_run)
    log = ClaudeAgent("m", 1.0, "api").run_session(tmp_path, 1, ("a", "b", "c"), False, tmp_path / "logs")
    assert [round(r.cost_usd, 3) for r in log.results] == [0.09, 0.006, 0.011]
    assert round(sum(r.cost_usd for r in log.results), 3) == 0.107


# --- the pass bars, exactly as accepted --------------------------------------------------------------


def _s(task: str, cond: str, run: int, broken: int, captured: int | None = None, catches: int | None = None):
    rules = ["r1", "r2", "r3"]
    scored = RunScore(task, cond, run, {r: i < broken for i, r in enumerate(rules)}, 0, False, 1.0)
    if captured is not None:
        scored.captured = {r: i < captured for i, r in enumerate(rules)}
        scored.captured_dead_end = True
    scored.gate_catches = catches
    return scored


def _batch(cond: str, broken: list[int], captured: list[int] | None = None, catches: list[int] | None = None):
    out = []
    for i, b in enumerate(broken):
        task = f"t{i % 3}"
        out.append(_s(task, cond, i // 3 + 1, b, None if captured is None else captured[i],
                      None if catches is None else catches[i]))  # fmt: skip
    return out


A15 = _batch("A", [2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 1])  # 22 in 15 runs, as full-1
E15 = _batch("E", [0] * 15)


def test_capture_passes_when_s_captures_halves_a_and_matches_n() -> None:
    s = _batch("S", [0] * 15, captured=[2] * 15)  # 2 rules + the dead end = 3 of 4 each run
    n = _batch("N", [0] * 15)
    v = decide_capture(s + n, A15 + E15)
    assert v.code == "pass" and v.claims == {"captures": True, "beats_self_notes": False}
    assert any("N matches S" in r for r in v.reasons)


def test_capture_beats_self_notes_only_by_a_clear_margin() -> None:
    s = _batch("S", [0] * 15, captured=[3] * 15)
    n = _batch("N", [1] * 15)  # 15 broken: clearly worse
    assert decide_capture(s + n, A15).claims == {"captures": True, "beats_self_notes": True}


@pytest.mark.parametrize(
    ("s_broken", "captured", "n_broken", "fails_on"),
    [
        ([0] * 15, [2] * 11 + [0] * 4, [0] * 15, "captured at least two-thirds"),  # too few runs capture enough
        ([1] * 15, [3] * 15, [2] * 15, "S at most half of A: no"),  # 15 > 22/2
        ([0] * 14 + [1], [3] * 15, [0] * 15, "S no worse than N: no"),
    ],
)
def test_capture_fails(s_broken, captured, n_broken, fails_on) -> None:
    v = decide_capture(_batch("S", s_broken, captured=captured) + _batch("N", n_broken), A15)
    assert v.code == "fail" and v.claims["captures"] is False and any(fails_on in r for r in v.reasons)


def test_capture_needs_the_baseline() -> None:
    assert decide_capture(_batch("S", [0] * 3, captured=[3] * 3) + _batch("N", [0] * 3), []).code == "not_measured"


def test_long_session_claims_only_after_e_slips() -> None:
    a = _batch("A", [1] * 9)
    quiet = decide_long(a + _batch("E", [0, 0, 1, 0, 0, 1, 0, 0, 0]) + _batch("C", [0] * 9, catches=[0] * 9))
    assert quiet.code == "not_measured" and quiet.claims == {"gate_catches_forgetting": False}
    caught = decide_long(a + _batch("E", [1] * 9) + _batch("C", [0] * 9, catches=[1, 0, 1, 0, 0, 0, 0, 0, 0]))
    assert caught.code == "pass" and caught.claims == {"gate_catches_forgetting": True}
    no_catches = decide_long(a + _batch("E", [1] * 9) + _batch("C", [0] * 9, catches=[0] * 9))
    assert no_catches.code == "fail"
    close = decide_long(a + _batch("E", [1] * 9) + _batch("C", [1] * 7 + [0, 0], catches=[1] * 9))
    assert close.code == "fail"  # 7 > 9 - 3


def test_summaries_print_the_study_verdicts() -> None:
    s = _batch("S", [0] * 3, captured=[3] * 3)
    text = summary(s + _batch("N", [0] * 3), counted=True, bar="capture", baseline=A15)
    assert "## Capture by run" in text and "## Verdict:" in text and "rules nobody" not in text
    assert "turns agreements only said in chat" in text
    long = summary(_batch("C", [0] * 3, catches=[1] * 3) + _batch("E", [1] * 3), counted=True, bar="long")
    assert "## Long session by run" in long and "catch what the agent forgets" in long
