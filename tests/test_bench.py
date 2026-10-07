"""The benchmark harness (ADR-20261006-c8b9): detectors, scoring and the pass bar, checked before
any paid run. End-to-end runs use a scripted FakeAgent instead of Claude Code."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from bench.harness import score
from bench.harness.agent import FakeAgent, parse_stream
from bench.harness.prepare import git, prepare
from bench.harness.tasks import CONDITIONS, TASK_IDS, load
from bench.harness.verdict import RunScore, decide
from bench.run import run_one, summary

T1 = load("t1_queue")
T2 = load("t2_prices")
HAVE_UV = shutil.which("uv") is not None
HAVE_NPM = shutil.which("npm") is not None


@pytest.fixture(autouse=True)
def _bench_cache(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Runs under a throwaway cache; the oracle's Python and vitest install are shared per session."""
    shared = tmp_path_factory.getbasetemp() / "bench-cache"
    monkeypatch.setattr("bench.harness.prepare.CACHE", shared)
    monkeypatch.setattr("bench.harness.score.CACHE", shared)
    monkeypatch.setattr("bench.run.CACHE", shared)


# --- task definitions ------------------------------------------------------------------------------


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_every_rule_has_a_visible_and_a_hidden_test(task_id: str) -> None:
    task = load(task_id)
    assert task.rules and len(task.sessions) == 3
    for rule in task.rules:
        assert (task.dir / "rules" / rule.file).is_file() and (task.dir / "oracle" / rule.file).is_file()
    assert "{{SRC}}" not in task.rule_source(task.rules[0], "oracle", 1)


def test_later_sessions_never_restate_the_rules() -> None:
    """The point of the benchmark: sessions 2-3 don't repeat what session 1 agreed."""
    for task in (T1, T2):
        later = " ".join(p for s in task.sessions[1:] for p in s).lower()
        assert "30 seconds" not in later and "at most once" not in later and "half-even" not in later
        assert "banker" not in later and "negative" not in later and "deadlock" not in later


def test_starting_code_does_not_restate_the_rules() -> None:
    """Calibration after the trial (ADR-20261006-c8b9): in condition A the only source of the rules
    must be session 1's prompt, as in a real project, not comments in the code."""
    giveaways = ("banker", "half-even", "half even", "ties go", "at most once", "already succeeded", "never exceed",
                 "negative", "30 seconds")  # fmt: skip
    for task in (T1, T2):
        for path in task.template.rglob("*"):
            if path.is_file() and path.suffix in (".py", ".ts", ".md") and "tests" not in path.parts:
                text = path.read_text().lower()
                assert not [g for g in giveaways if g in text], path


# --- dead-end detectors (exact definitions) ---------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "hit"),
    [
        ("import threading\nthreading.Thread(target=f).start()\n", True),
        ("import threading as th\nth.Timer(1, f)\n", True),
        ("from threading import Thread as T\nT(target=f)\n", True),
        ("from concurrent.futures import ThreadPoolExecutor\nwith ThreadPoolExecutor(4) as ex: pass\n", True),
        ("import concurrent.futures as cf\ncf.ThreadPoolExecutor()\n", True),
        ("import concurrent.futures\nconcurrent.futures.ThreadPoolExecutor()\n", True),
        ("import threading\nlock = threading.Lock()\n", False),
        ("from concurrent.futures import ProcessPoolExecutor\nProcessPoolExecutor()\n", False),
        ("# threading.Thread( in a comment\nx = 'threading.Thread('\n", False),
        ("def broken(:\n", False),
    ],
)
def test_t1_dead_end_detector(source: str, hit: bool) -> None:
    assert score.t1_dead_end(source) is hit


@pytest.mark.parametrize(
    ("source", "hit"),
    [
        ("return Number(x.toFixed(2));", True),
        ("const c = Math.round(total * 100) / 100;", True),
        ("const c = Math.round( total*100 )/100;", True),
        ("return roundCents(cents * (1 + taxRate));", False),
        ("const c = Math.round(cents);", False),
        ("const whole = Math.floor(cents / 100);", False),
    ],
)
def test_t2_dead_end_detector(source: str, hit: bool) -> None:
    assert score.t2_dead_end(source) is hit


def test_templates_start_without_the_dead_end() -> None:
    assert not score.dead_end_reappeared(T1, T1.template)
    assert not score.dead_end_reappeared(T2, T2.template)


# --- tampering -------------------------------------------------------------------------------------


def _repo_with_rule_test(tmp_path: Path) -> Path:
    work = tmp_path / "w"
    (work / "tests/rules").mkdir(parents=True)
    (work / "tests/rules/test_r.py").write_text("def test_r():\n    assert True\n")
    (work / "tests/test_other.py").write_text("def test_o():\n    assert True\n")
    git(work, "init", "-q", "-b", "main")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "start")
    git(work, "tag", "bench-start")
    return work


def test_tampering_counts_edits_deletions_and_new_skips(tmp_path: Path) -> None:
    work = _repo_with_rule_test(tmp_path)
    assert score.tampering(work, ["tests/rules/test_r.py"]) == 0
    (work / "tests/rules/test_r.py").write_text("def test_r():\n    assert 1\n")
    assert score.tampering(work, ["tests/rules/test_r.py"]) == 1
    (work / "tests/test_other.py").write_text(
        "import pytest\n\n@pytest.mark.skip\ndef test_o():\n    pytest.skip('later')\n"
    )
    assert score.tampering(work, ["tests/rules/test_r.py"]) == 3  # edit + 2 skip markers
    (work / "tests/rules/test_r.py").unlink()
    (work / "tests/new_feature.test.ts").write_text("it.skip('x', () => {});\n")
    assert score.tampering(work, ["tests/rules/test_r.py"]) == 4  # deletion, 2 py markers, 1 ts marker


# --- the pass bar ----------------------------------------------------------------------------------


def _scores(spec: dict[str, tuple[int, int, int, float]], tasks: tuple[str, ...] = ("t1",)) -> list[RunScore]:
    """spec: condition -> (violations, tampering, dead ends, cost per run), spread over 1 run per task."""
    out = []
    for cond, (v, tamper, dead, cost) in spec.items():
        for i, task in enumerate(tasks):
            share = v // len(tasks) + (1 if i < v % len(tasks) else 0)
            out.append(RunScore(task, cond, 1, {f"r{n}": True for n in range(share)}, tamper if i == 0 else 0,
                                bool(dead) and i == 0, cost))  # fmt: skip
    return out


@pytest.mark.parametrize(
    ("spec", "code"),
    [
        ({"A": (1, 0, 0, 1.0), "B": (1, 0, 0, 1.0), "C": (0, 0, 0, 1.0), "D": (0, 0, 0, 1.0)}, "redo"),
        ({"A": (12, 0, 1, 1.0), "B": (7, 0, 1, 1.1), "C": (3, 0, 0, 1.2), "D": (9, 2, 1, 1.0)}, "pass"),
        ({"A": (12, 0, 1, 1.0), "B": (7, 0, 1, 1.1), "C": (3, 0, 0, 1.8), "D": (9, 2, 1, 1.0)}, "pass_cost_followup"),
        ({"A": (12, 0, 1, 1.0), "B": (7, 0, 0, 1.1), "C": (4, 1, 0, 1.2), "D": (4, 1, 0, 1.0)}, "pivot_positioning"),
        ({"A": (12, 0, 1, 1.0), "B": (10, 0, 1, 1.1), "C": (7, 0, 0, 1.2), "D": (9, 0, 1, 1.0)}, "kill_or_rethink"),
        ({"A": (12, 0, 1, 1.0), "B": (7, 0, 1, 1.1), "C": (3, 0, 0, 2.5), "D": (9, 2, 1, 1.0)}, "kill_or_rethink"),
    ],
    ids=["too-easy", "clear-win", "pricey-win", "same-as-plain-tests", "does-not-help", "too-expensive"],
)
def test_pass_bar(spec: dict, code: str) -> None:
    assert decide(_scores(spec)).code == code


def test_c_worse_than_a_on_one_task_is_left_to_the_owner() -> None:
    scores = _scores({"A": (12, 0, 1, 1.0), "B": (7, 0, 1, 1.0), "C": (4, 0, 0, 1.0), "D": (9, 2, 1, 1.0)}, ("t1",))
    scores.append(RunScore("t2", "A", 1, {}, 0, False, 1.0))
    scores.append(RunScore("t2", "C", 1, {"r": True}, 0, False, 1.0))
    assert decide(scores).code == "owner_call"


def test_parse_stream_reads_the_result_event() -> None:
    lines = ['{"type":"system"}', "not json", '{"type":"result","total_cost_usd":0.12,"num_turns":3}']
    assert parse_stream(lines)["total_cost_usd"] == 0.12 and parse_stream([]) == {}


# --- the hidden oracle on real code ----------------------------------------------------------------


@pytest.mark.skipif(not HAVE_UV, reason="uv not installed")
def test_t1_oracle_passes_the_template_and_catches_a_broken_cap(tmp_path: Path) -> None:
    work = tmp_path / "t1"
    shutil.copytree(T1.template, work)
    assert score.oracle(T1, work) == {"retry_cap": True, "at_most_once": True, "enqueue_signature": True}
    queue = work / "src/jobqueue/queue.py"
    queue.write_text(queue.read_text().replace("MAX_DELAY = 30.0", "MAX_DELAY = 300.0"))
    assert score.oracle(T1, work) == {"retry_cap": False, "at_most_once": True, "enqueue_signature": True}


@pytest.mark.skipif(not HAVE_UV, reason="uv not installed")
def test_t1_oracle_fails_every_rule_when_the_code_no_longer_imports(tmp_path: Path) -> None:
    work = tmp_path / "t1"
    shutil.copytree(T1.template, work)
    (work / "src/jobqueue/queue.py").write_text("this is not python\n")
    assert not any(score.oracle(T1, work).values())


@pytest.mark.skipif(not HAVE_NPM, reason="npm not installed")
def test_t2_oracle_passes_the_template_and_catches_half_up_rounding(tmp_path: Path) -> None:
    work = tmp_path / "t2"
    shutil.copytree(T2.template, work)
    assert score.oracle(T2, work) == {"rounding": True, "non_negative": True}
    prices = work / "src/prices.ts"
    prices.write_text(prices.read_text().replace("return roundCents(cents * (1 + taxRate));",
                                                 "return Math.round(cents * (1 + taxRate));"))  # fmt: skip
    assert score.oracle(T2, work) == {"rounding": False, "non_negative": True}


# --- end to end with a scripted agent --------------------------------------------------------------


def _raise_cap_and_add_a_pool(work: Path) -> None:
    queue = work / "src/jobqueue/queue.py"
    text = queue.read_text().replace("MAX_DELAY = 30.0", "MAX_DELAY = 600.0")
    queue.write_text(
        text + "\nfrom concurrent.futures import ThreadPoolExecutor  # noqa: E402\n\n_POOL = ThreadPoolExecutor(4)\n"
    )


@pytest.mark.skipif(not HAVE_UV, reason="uv not installed")
@pytest.mark.parametrize("condition", CONDITIONS)
def test_end_to_end_with_a_scripted_agent(tmp_path: Path, condition: str) -> None:
    out = tmp_path / "results" / "fake"
    agent = FakeAgent({2: _raise_cap_and_add_a_pool})
    s = run_one(T1, condition, 1, agent, out)
    assert s.violations == {"retry_cap": True, "at_most_once": False, "enqueue_signature": False}
    assert s.dead_end and s.tampering == 0 and s.cost_usd == pytest.approx(0.09)
    work = Path(score.CACHE) / "runs" / "fake" / f"t1_queue-{condition}-1"
    has_ledger = (work / ".seamspec/config.toml").is_file()
    assert has_ledger is (condition in ("B", "C"))
    assert (work / ".claude/settings.json").is_file() is (condition == "D")
    if condition == "C":
        assert (work / ".git/hooks/pre-commit").is_file()
        from seamspec.core.config import load_config
        from seamspec.core.store import Store

        assert load_config(work).mode == "enforced"
        locked = [i for i in Store(work).load_all("inv") if getattr(i, "status", None) and i.status.value == "LOCKED"]
        assert len(locked) == len(T1.rules)
    assert "| t1_queue |" in summary([s], counted=False)


@pytest.mark.skipif(not HAVE_UV, reason="uv not installed")
def test_rule_tests_pass_on_the_untouched_code_in_every_condition(tmp_path: Path) -> None:
    """If a visible rule test failed at the start, C and D would block the agent for nothing."""
    for condition in ("C", "D"):
        prepared = prepare(T1, condition, tmp_path / condition)
        assert prepared.rule_test_paths and score.tampering(prepared.work, prepared.rule_test_paths) == 0


def _coupon_without_a_floor_and_simpler_rounding(work: Path) -> None:
    prices = work / "src/prices.ts"
    text = prices.read_text().replace("cents - Math.min(discount.cents, cents)", "cents - discount.cents")
    text = text.replace(
        "return roundCents(cents * (1 + taxRate));", "return Number((cents * (1 + taxRate)).toFixed(0));"
    )
    prices.write_text(text)


@pytest.mark.skipif(not (HAVE_UV and HAVE_NPM), reason="uv or npm not installed")
@pytest.mark.parametrize("condition", ["C", "D"])
def test_t2_end_to_end_with_a_scripted_agent(tmp_path: Path, condition: str) -> None:
    s = run_one(T2, condition, 1, FakeAgent({3: _coupon_without_a_floor_and_simpler_rounding}), tmp_path / "out")
    assert s.violations == {"rounding": True, "non_negative": True} and s.dead_end and s.tampering == 0


# --- billing (the owner's choice: never bill the wrong account) -------------------------------------


def _fake_claude(monkeypatch: pytest.MonkeyPatch, source: str | None) -> list[dict]:
    """Replace `claude -p` with a canned stream; return the environments it was called with."""
    import subprocess as sp

    from bench.harness import agent as agent_mod

    seen: list[dict] = []
    init = {"type": "system", "subtype": "init"} | ({"apiKeySource": source} if source is not None else {})
    stream = "\n".join([json.dumps(init), json.dumps({"type": "result", "total_cost_usd": 0.05, "num_turns": 2})])

    def fake_run(cmd, **kw):
        seen.append(kw["env"])
        return sp.CompletedProcess(cmd, 0, stdout=stream, stderr="")

    monkeypatch.setattr(agent_mod.subprocess, "run", fake_run)
    return seen


def test_plan_billing_removes_the_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bench.harness.agent import ClaudeAgent

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    seen = _fake_claude(monkeypatch, "none")
    log = ClaudeAgent("m", 1.0, "plan").run_session(tmp_path, 1, ("hi",), False, tmp_path / "logs")
    assert "ANTHROPIC_API_KEY" not in seen[0] and log.results[0].cost_usd == 0.05


def test_api_billing_keeps_the_key_and_needs_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bench.harness.agent import BillingMismatch, ClaudeAgent

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(BillingMismatch, match="needs ANTHROPIC_API_KEY"):
        ClaudeAgent("m", 1.0, "api")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    seen = _fake_claude(monkeypatch, "ANTHROPIC_API_KEY")
    log = ClaudeAgent("m", 1.0, "api").run_session(tmp_path, 1, ("hi",), False, tmp_path / "logs")
    assert seen[0]["ANTHROPIC_API_KEY"] == "sk-test-not-real"
    assert log.results[0].api_key_source == "ANTHROPIC_API_KEY"


@pytest.mark.parametrize(("billing", "source"), [("api", "none"), ("plan", "ANTHROPIC_API_KEY")])
def test_a_billing_mismatch_stops_the_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, billing: str, source: str
) -> None:
    from bench.harness.agent import BillingMismatch, ClaudeAgent

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    _fake_claude(monkeypatch, source)
    with pytest.raises(BillingMismatch, match="Stopping"):
        ClaudeAgent("m", 1.0, billing).run_session(tmp_path, 1, ("hi", "again"), False, tmp_path / "logs")


def test_runner_refuses_api_billing_without_a_key(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from bench.run import main

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main(["--model", "m", "--label", "x", "--billing", "api", "--yes", "--tasks", "t1_queue"]) == 2
    assert "needs ANTHROPIC_API_KEY" in capsys.readouterr().out
