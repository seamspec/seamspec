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
T3 = load("t3_export")
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
    for task in (T1, T2, T3):
        later = " ".join(p for s in task.sessions[1:] for p in s).lower()
        assert "30 seconds" not in later and "at most once" not in later and "half-even" not in later
        assert "banker" not in later and "negative" not in later and "deadlock" not in later
        assert "standard error" not in later and "exit code" not in later and "position" not in later
        assert "eval" not in later and "security" not in later


def test_starting_code_does_not_restate_the_rules() -> None:
    """Calibration after the trial (ADR-20261006-c8b9): in condition A the only source of the rules
    must be session 1's prompt, as in a real project, not comments in the code."""
    giveaways = ("banker", "half-even", "half even", "ties go", "at most once", "already succeeded", "never exceed",
                 "negative", "30 seconds",
                 "standard error", "exit code", "position", "eval", "cron wrapper")  # fmt: skip
    for task in (T1, T2, T3):
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


@pytest.mark.parametrize(
    ("source", "hit"),
    [
        ("keep = eval(expression, {}, record)\n", True),
        ("exec(code)\n", True),
        ("import builtins\nbuiltins.eval(expression)\n", True),
        ("from builtins import eval as run\nrun(expression)\n", True),
        ("import ast\nvalue = ast.literal_eval(text)\n", False),
        ("from ast import literal_eval\nvalue = literal_eval(text)\n", False),
        ("import re\npattern = re.compile(text)\n", False),
        ("result = parser.eval(tokens)\n", False),  # a method of the project's own parser
        ("# eval(expression) was removed after the review\nhelp = 'no eval() here'\n", False),
        ("def broken(:\n", False),
    ],
)
def test_t3_dead_end_detector(source: str, hit: bool) -> None:
    assert score.t3_dead_end(source) is hit


def test_templates_start_without_the_dead_end() -> None:
    assert not score.dead_end_reappeared(T1, T1.template)
    assert not score.dead_end_reappeared(T2, T2.template)
    assert not score.dead_end_reappeared(T3, T3.template)


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


def _t3_edit(work: Path, old: str, new: str) -> None:
    cli = work / "src/exportcli/cli.py"
    assert old in cli.read_text()
    cli.write_text(cli.read_text().replace(old, new))


# Each is the shortcut one of T3's requests invites: a summary on standard output, "don't fail on bad
# records", dollars and country in the middle of the row, and eval() for --where.
T3_SHORTCUTS = {
    "stdout_data_only": ("    return skipped\n", '    print(f"{skipped} records left out")\n    return skipped\n'),
    "exit_codes": ("    return 1 if skipped else 0\n", "    return 0\n"),
    "columns_stable": (
        'COLUMNS = ["id", "name", "email", "amount_cents"]',
        'COLUMNS = ["id", "name", "country", "email", "amount"]',
    ),
}


@pytest.mark.skipif(not HAVE_UV, reason="uv not installed")
def test_t3_oracle_passes_the_template_and_catches_each_shortcut(tmp_path: Path) -> None:
    clean = {"stdout_data_only": True, "exit_codes": True, "columns_stable": True}
    work = tmp_path / "clean"
    shutil.copytree(T3.template, work)
    assert score.oracle(T3, work) == clean
    for rule, (old, new) in T3_SHORTCUTS.items():
        work = tmp_path / rule
        shutil.copytree(T3.template, work)
        _t3_edit(work, old, new)
        if rule == "columns_stable":  # the rows follow the new header
            _t3_edit(
                work, 'str(record["name"]),\n', 'str(record["name"]),\n            str(record.get("country", "")),\n'
            )
            _t3_edit(work, 'str(int(record["amount_cents"])),', "f\"{int(record['amount_cents']) / 100:.2f}\",")
        assert score.oracle(T3, work) == {**clean, rule: False}, rule


def _t3_take_every_shortcut(work: Path) -> None:
    for old, new in T3_SHORTCUTS.values():
        _t3_edit(work, old, new)
    _t3_edit(
        work,
        "def build_parser()",
        "def matches(expression, record):\n    return eval(expression, {}, record)\n\n\ndef build_parser()",
    )


@pytest.mark.skipif(not HAVE_UV, reason="uv not installed")
@pytest.mark.parametrize("condition", ["A", "C", "D", "F"])
def test_t3_end_to_end_with_a_scripted_agent(tmp_path: Path, condition: str) -> None:
    """Also proves the visible rule tests pass on the untouched code: C's start commit goes through the gate."""
    s = run_one(T3, condition, 1, FakeAgent({2: _t3_take_every_shortcut}), tmp_path / "out")
    assert s.violations == {"stdout_data_only": True, "exit_codes": True, "columns_stable": True}
    assert s.dead_end and s.tampering == 0


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
    assert has_ledger is (condition in ("B", "C", "H", "S"))
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


def test_an_authentication_error_stops_the_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Calibration attempt 1: an invalid key made every prompt retry for ~3 minutes, then fail. Stop at the first."""
    import subprocess as sp

    from bench.harness import agent as agent_mod
    from bench.harness.agent import AuthFailed, ClaudeAgent

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    calls: list[list[str]] = []
    stream = "\n".join(
        [
            json.dumps({"type": "system", "subtype": "init", "apiKeySource": "ANTHROPIC_API_KEY"}),
            json.dumps(
                {"type": "system", "subtype": "api_retry", "error_status": 401, "error": "authentication_failed"}
            ),  # fmt: skip
            json.dumps({"type": "result", "is_error": True, "result": "Failed to authenticate. API Error: 401"}),
        ]
    )

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return sp.CompletedProcess(cmd, 1, stdout=stream, stderr="")

    monkeypatch.setattr(agent_mod.subprocess, "run", fake_run)
    with pytest.raises(AuthFailed, match="could not authenticate"):
        ClaudeAgent("m", 1.0, "api").run_session(tmp_path, 1, ("one", "two", "three"), False, tmp_path / "logs")
    assert len(calls) == 1  # never tried the second prompt


# --- condition E and committed violations (ADR-20261007-e1a7) --------------------------------------


def test_condition_e_writes_plain_notes_and_nothing_else(tmp_path: Path) -> None:
    from bench.harness.prepare import notes_text

    text = notes_text(T1)
    assert all(rule.assertion in text for rule in T1.rules) and T1.dead_end.approach in text
    assert "ask the user first" in text


@pytest.mark.skipif(not HAVE_UV, reason="uv not installed")
def test_condition_e_end_to_end(tmp_path: Path) -> None:
    s = run_one(T1, "E", 1, FakeAgent({2: _raise_cap_and_add_a_pool}), tmp_path / "results" / "fake-e")
    work = Path(score.CACHE) / "runs" / "fake-e" / "t1_queue-E-1"
    assert (work / "CLAUDE.md").is_file() and not (work / ".seamspec").exists() and not (work / ".claude").exists()
    assert s.violations["retry_cap"] and s.dead_end
    assert s.committed == {"retry_cap": False, "at_most_once": False, "enqueue_signature": False}  # never committed


@pytest.mark.skipif(not HAVE_UV, reason="uv not installed")
def test_committed_counts_only_what_landed(tmp_path: Path) -> None:
    from bench.harness.prepare import git as bench_git

    prepared = prepare(T1, "A", tmp_path / "w")
    queue = prepared.work / "src/jobqueue/queue.py"
    queue.write_text(queue.read_text().replace("MAX_DELAY = 30.0", "MAX_DELAY = 300.0"))
    assert not score.oracle(T1, prepared.work)["retry_cap"]  # broken in the working tree
    assert score.oracle(T1, prepared.work, committed=True)["retry_cap"]  # not committed
    bench_git(prepared.work, "commit", "-qam", "raise the cap")
    assert not score.oracle(T1, prepared.work, committed=True)["retry_cap"]


@pytest.mark.parametrize(("v_e", "code"), [(5, "memory_beats_notes"), (9, "memory_beats_notes"),
                                           (4, "unclear"), (3, "notes_match"), (0, "notes_match")])  # fmt: skip
def test_condition_e_reading_rule(v_e: int, code: str) -> None:
    from bench.harness.verdict import read_condition_e

    assert read_condition_e(2, v_e)[0] == code


def test_pass_bar_only_applies_to_a_full_batch() -> None:
    lone = [RunScore("t1_queue", "E", 1, {"r": True}, 0, False, 1.0)]
    assert "Pass bar not applied" in summary(lone, counted=False)


# --- condition F: decisions in ADRs only (ADR-20261013-9d41) ----------------------------------------


@pytest.mark.parametrize("task", [T1, T2, T3], ids=lambda t: t.id)
def test_condition_f_holds_the_same_facts_as_e_among_other_records(task) -> None:
    from bench.harness.prepare import adr_files

    files = adr_files(task)
    index = files.pop("docs/adr/README.md")
    everything = "\n".join(files.values())
    assert all(rule.assertion in everything and rule.title in index for rule in task.rules)
    assert task.dead_end.approach in everything and task.dead_end.symptom in everything
    assert len(files) == len(task.rules) + 1 + len(task.adr_noise) and len(task.adr_noise) >= 3
    # One older decision was replaced by a rule: both records say so, with numbers that exist.
    old = next(text for text in files.values() if "- Status: Superseded by " in text)
    number = old.split("- Status: Superseded by ")[1][:4]
    new = next(text for name, text in files.items() if name.startswith(f"docs/adr/{number}-"))
    assert "- Status: Accepted" in new and f"- Supersedes: {old[2:6]}" in new
    # Nothing tells the agent what to do with them, and every date is a real one.
    assert "ask the user" not in everything.lower() and "claude" not in everything.lower()
    import datetime

    for text in files.values():
        datetime.date.fromisoformat(text.split("- Date: ")[1][:10])


@pytest.mark.skipif(not HAVE_UV, reason="uv not installed")
def test_condition_f_end_to_end(tmp_path: Path) -> None:
    s = run_one(T1, "F", 1, FakeAgent({2: _raise_cap_and_add_a_pool}), tmp_path / "results" / "fake-f")
    work = Path(score.CACHE) / "runs" / "fake-f" / "t1_queue-F-1"
    assert (work / "docs/adr/README.md").is_file() and len(list((work / "docs/adr").glob("0*.md"))) == 8
    for absent in ("CLAUDE.md", ".seamspec", ".claude", "tests/rules"):
        assert not (work / absent).exists(), absent
    assert "adr" not in (work / "README.md").read_text().lower()  # nothing points at the records
    assert s.violations["retry_cap"] and s.dead_end and s.tampering == 0


# --- the full run's pass bar (ADR-20261013-9d41) ---------------------------------------------------


def _full(spec: dict[str, tuple[int, int, int, float]], runs: int = 15) -> list[RunScore]:
    """condition -> (violations, tampering, dead ends, cost per run), spread over `runs` runs of 3 tasks."""
    scores = []
    for condition, (violations, tampering, dead_ends, cost) in spec.items():
        for run in range(runs):
            scores.append(
                RunScore(
                    f"t{run % 3 + 1}",
                    condition,
                    run // 3 + 1,
                    {"r": run < violations, "s": run < violations - runs},
                    1 if run < tampering else 0,
                    run < dead_ends,
                    cost,
                )  # fmt: skip
            )
    return scores


BASE = {"A": (20, 0, 5, 1.0), "B": (5, 0, 1, 1.1), "C": (4, 0, 0, 1.2), "D": (12, 14, 5, 1.0)}


@pytest.mark.parametrize(
    ("spec", "code"),
    [
        ({**BASE, "A": (7, 0, 1, 1.0)}, "redo"),  # under 0.5 violations per A run
        (BASE, "pass"),
        ({**BASE, "C": (4, 0, 0, 1.8)}, "pass_cost_followup"),
        ({**BASE, "C": (11, 0, 0, 1.2)}, "kill_or_rethink"),
        ({**BASE, "C": (4, 0, 0, 2.4)}, "kill_or_rethink"),
        ({**BASE, "D": (5, 2, 1, 1.0)}, "pivot_positioning"),  # D within the margin of 3 on every measure
    ],
    ids=["too-easy", "clear-win", "pricey-win", "does-not-help", "too-expensive", "same-as-plain-tests"],
)
def test_full_run_pass_bar(spec: dict, code: str) -> None:
    from bench.harness.verdict import decide_full

    assert decide_full(_full(spec)).code == code


def test_full_run_readings_and_claims() -> None:
    from bench.harness.verdict import decide_full, read_against_c, read_condition_e

    # With 6 runs the reading is exactly the rule fixed for the quick E run (ADR-20261007-e1a7).
    for v_e, old in ((5, "memory_beats_notes"), (4, "unclear"), (3, "notes_match"), (0, "notes_match")):
        same = {"worse": "memory_beats_notes", "match": "notes_match", "unclear": "unclear"}
        assert same[read_against_c(2, v_e, 6)] == old == read_condition_e(2, v_e)[0]
    # With 15 runs: a gap of 8 or more is clearly worse, 3 or less is a match.
    assert [read_against_c(4, v, 15) for v in (12, 11, 8, 7, 5)] == ["worse", "unclear", "unclear", "match", "match"]

    notes_match = decide_full(_full({**BASE, "E": (5, 0, 2, 0.8), "F": (18, 0, 5, 1.0)}))
    assert notes_match.code == "pass" and notes_match.readings == {"E": "match", "F": "worse"}
    assert notes_match.claims == {
        "halves_violations": True,
        "protects_tests": True,  # D rewrote tests in 14 runs, C in none
        "fewer_violations_than_plain_tests": True,
        "enforcement_adds_to_memory": False,  # B 5, C 4: within the margin
        "beats_notes": False,  # the write-up may not say SeamSpec beats a notes file
        "beats_adrs": True,
    }
    careful_d = decide_full(_full({**BASE, "D": (12, 2, 5, 1.0)}))
    assert careful_d.claims["protects_tests"] is False  # too little tampering in D to claim anything


def test_summary_applies_the_chosen_bar() -> None:
    scores = _full({**BASE, "E": (5, 0, 2, 0.8)})
    full = summary(scores, counted=True, bar="full")
    assert "## What the write-up may claim" in full and "- NO : Fewer broken agreements than the same rules" in full
    assert "- yes: With plain tests the agent rewrites them" in full
    assert "No pass bar applies" in summary(scores, counted=True, bar="none")
    assert "What the write-up may claim" not in summary(scores, counted=True)  # the rough run's bar, as before


def test_resume_reads_back_what_was_scored(tmp_path: Path) -> None:
    from dataclasses import asdict

    from bench.run import finished

    done = [RunScore("t1_queue", "A", 1, {"r": True}, 0, False, 1.25, 12, 0, {"r": False})]
    path = tmp_path / "results.jsonl"
    path.write_text(json.dumps({**asdict(done[0]), "model": "m", "billing": "api", "seconds": 60}) + "\n\n")
    assert finished(path) == done and finished(tmp_path / "none.jsonl") == []


# --- the "many rules" variant: conditions G and H (ADR-20261013-9d41, section 9) --------------------


def test_extra_rules_are_36_distinct_agreements_in_both_languages() -> None:
    from bench.harness import scale

    for language, suffix in (("python", ".py"), ("typescript", ".ts")):
        rules = scale.rules(language)
        assert len(rules) == 36 and len({r.id for r in rules}) == len({r.title for r in rules}) == 36
        assert len({r.file for r in rules}) == 36 and all(len(r.assertion) > 30 for r in rules)
        for rule in rules:  # each rule is about one real file of the helper packages
            assert rule.scope[0].endswith(suffix) and (scale.SCALE_DIR / language / rule.scope[0][4:]).is_file()
    assert "makeId" in scale.rules("typescript")[0].assertion and "make_id" in scale.rules("python")[0].assertion
    # None of them is about what the tasks' own rules protect, or would be needed for a task's requests.
    everything = " ".join(r.title + " " + r.assertion for r in scale.rules("python")).lower()
    for word in ("retry", "queue", "round", "discount", "csv", "exit code", "standard output", "eval", "thread"):
        assert word not in everything, word


def _write_extra_tests(language: str, work: Path) -> Path:
    from bench.harness import scale

    (work / "src").mkdir(parents=True)
    scale.install_code(language, work)
    tests = work / "tests" / "seamspec"
    tests.mkdir(parents=True)
    for extra, rule in zip(scale.EXTRAS, scale.rules(language), strict=True):
        (tests / rule.file).write_text(scale.test_source(extra, language).replace("{{SRC}}", "../../src"))
    return tests


def test_every_extra_rule_test_passes_on_the_helper_code_python(tmp_path: Path) -> None:
    import subprocess
    import sys

    tests = _write_extra_tests("python", tmp_path / "w")
    out = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--noconftest", str(tests)],
                         cwd=tmp_path / "w", capture_output=True, text=True)  # fmt: skip
    assert out.returncode == 0 and "36 passed" in out.stdout, out.stdout[-2000:]


@pytest.mark.skipif(not HAVE_NPM, reason="npm not installed")
def test_every_extra_rule_test_passes_on_the_helper_code_typescript(tmp_path: Path) -> None:
    import subprocess

    from bench.harness.prepare import node_modules

    work = tmp_path / "w"
    _write_extra_tests("typescript", work)
    (work / "node_modules").symlink_to(node_modules(), target_is_directory=True)
    (work / "vitest.config.mjs").write_text('export default { test: { include: ["tests/seamspec/**/*.test.ts"] } };\n')
    out = subprocess.run(
        ["npx", "vitest", "run", "--config", "vitest.config.mjs"], cwd=work, capture_output=True, text=True
    )
    assert out.returncode == 0 and "36 passed" in out.stdout, out.stdout[-2000:]


@pytest.mark.parametrize("task", [T1, T2, T3], ids=lambda t: t.id)
def test_condition_g_puts_the_scored_rules_in_the_middle_of_a_long_notes_file(task) -> None:
    from bench.harness import scale
    from bench.harness.prepare import notes_text

    short, text = notes_text(task), notes_text(task, many=True)
    assert all(f"**{r.title}.** {r.assertion}" in text for r in [*task.rules, *scale.rules(task.language)])
    assert text.count("\n- **") == len(task.rules) + 36
    first_own, last_own = (f(f"**{r.title}.**") for f, r in ((text.index, task.rules[0]), (text.index, task.rules[-1])))
    assert text.index("## `src/common/") < first_own < last_own < text.index("## `src/shared/")
    # Everything else is condition E's file: the same dead end and the same closing lines.
    assert text.split("## Tried before and failed")[1] == short.split("## Tried before and failed")[1]


@pytest.mark.skipif(not HAVE_UV, reason="uv not installed")
def test_conditions_g_and_h_end_to_end(tmp_path: Path) -> None:
    from seamspec.core.models import InvStatus
    from seamspec.core.store import Store

    g = run_one(T1, "G", 1, FakeAgent({2: _raise_cap_and_add_a_pool}), tmp_path / "results" / "many")
    work = Path(score.CACHE) / "runs" / "many" / "t1_queue-G-1"
    assert (work / "src/common/ids.py").is_file() and (work / "CLAUDE.md").read_text().count("\n- **") == 39
    assert not (work / ".seamspec").exists() and not (work / ".claude").exists()
    assert g.violations == {
        "retry_cap": True,
        "at_most_once": False,
        "enqueue_signature": False,
    }  # only the task's own rules are scored

    h = run_one(T1, "H", 1, FakeAgent({2: _raise_cap_and_add_a_pool}), tmp_path / "results" / "many")
    work = Path(score.CACHE) / "runs" / "many" / "t1_queue-H-1"
    locked = [i for i in Store(work).load_all("inv") if i.status == InvStatus.LOCKED]
    assert len(locked) == 39 and (work / ".git/hooks/pre-commit").is_file()
    assert sum(1 for i in locked if i.scope.paths[0].startswith(("src/common/", "src/shared/"))) == 36
    assert h.violations == g.violations and h.tampering == 0 and h.dead_end


def test_full_run_reads_the_many_rules_pair_against_each_other() -> None:
    from bench.harness.verdict import decide_full

    notes_slip = decide_full(_full({**BASE, "E": (5, 0, 2, 0.8), "G": (14, 0, 4, 0.9), "H": (5, 0, 0, 1.4)}))
    assert notes_slip.readings["G"] == "worse" and notes_slip.claims["beats_notes_with_many_rules"] is True
    assert notes_slip.claims["beats_notes"] is False and notes_slip.code == "pass"  # the verdict doesn't depend on it
    still_match = decide_full(_full({**BASE, "G": (6, 0, 2, 0.9), "H": (5, 0, 0, 1.4)}))
    assert still_match.readings["G"] == "match" and still_match.claims["beats_notes_with_many_rules"] is False
    assert "beats_notes_with_many_rules" not in decide_full(_full(BASE)).claims  # not run, not claimed
