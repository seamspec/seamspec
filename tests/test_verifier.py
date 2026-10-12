"""Verifier against real pytest runs in throwaway repos (SPEC §12.2, §12A.4)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from seamspec.core import reports, verifier
from seamspec.core.config import RunnerCfg, load_config, parse_config
from seamspec.core.models import InvStatus

from .verify_helpers import write_locked

PASS = "from src.queue import backoff_delay\n\ndef test_cap():\n    assert backoff_delay(100) <= 30\n"
FAIL = "def test_fails():\n    assert 1 == 2\n"


def run(root: Path, invs, **kw) -> verifier.VerifyReport:
    return verifier.run(root, load_config(root), invs, **kw)


# --- end to end with pytest -------------------------------------------------------------------


def test_passing_harness_imports_project_code(py_repo: Path) -> None:
    inv = write_locked(py_repo, load_config(py_repo), "inv_00000001", PASS)
    report = run(py_repo, [inv])
    assert report.passed, report.to_dict()
    assert report.failing_ids == []


def test_failure_is_attributed_to_the_right_rule(py_repo: Path) -> None:
    cfg = load_config(py_repo)
    good = write_locked(py_repo, cfg, "inv_00000001", PASS)
    bad = write_locked(py_repo, cfg, "inv_00000002", FAIL)
    report = run(py_repo, [good, bad])
    assert not report.passed
    assert report.failing_ids == ["inv_00000002"]
    assert "assert 1 == 2" in report.results[0].output


def test_collection_error_blames_only_the_broken_harness(py_repo: Path) -> None:
    cfg = load_config(py_repo)
    broken = write_locked(py_repo, cfg, "inv_00000001", "import does_not_exist\n\ndef test_x():\n    pass\n")
    good = write_locked(py_repo, cfg, "inv_00000002", PASS)
    report = run(py_repo, [broken, good])
    assert report.failing_ids == ["inv_00000001"]


@pytest.mark.parametrize(
    "code",
    [
        "import pytest\n\n@pytest.mark.skip\ndef test_s():\n    pass\n",  # all skipped
        "x = 1\n",  # no tests at all
        "import pytest\npytest.skip('nope', allow_module_level=True)\n",  # module-level skip
    ],
)
def test_empty_or_all_skipped_harness_fails(py_repo: Path, code: str) -> None:
    cfg = load_config(py_repo)
    empty = write_locked(py_repo, cfg, "inv_00000001", code)
    good = write_locked(py_repo, cfg, "inv_00000002", PASS)
    report = run(py_repo, [empty, good])
    assert report.failing_ids == ["inv_00000001"]
    assert "Ran no tests, or skipped every test" in report.results[0].output


STUBBING_CONFTEST = (
    "import pytest\n\n@pytest.hookimpl(tryfirst=True)\n"
    "def pytest_runtest_call(item):\n    pytest.skip('stubbed by a conftest')\n"
)


def test_project_conftest_and_addopts_are_ignored(py_repo: Path) -> None:
    # Root conftest + addopts, and a conftest planted next to the harnesses (e.g. written with Bash,
    # past the PreToolUse protection): --noconftest and SeamSpec's own ini keep all of them out.
    (py_repo / "conftest.py").write_text(STUBBING_CONFTEST)
    (py_repo / ".seamspec/tests").mkdir(parents=True, exist_ok=True)
    (py_repo / ".seamspec/tests/conftest.py").write_text(STUBBING_CONFTEST)
    with (py_repo / "pyproject.toml").open("a") as f:
        f.write('\n[tool.pytest.ini_options]\naddopts = "-k nothing_matches"\n')
    inv = write_locked(py_repo, load_config(py_repo), "inv_00000001", PASS)
    assert run(py_repo, [inv]).passed


def test_harness_works_from_any_cwd(py_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inv = write_locked(py_repo, load_config(py_repo), "inv_00000001", PASS)
    monkeypatch.chdir(py_repo / "src")
    assert run(py_repo, [inv]).passed


# --- integrity and runner config ---------------------------------------------------------------


def test_modified_harness_is_an_integrity_failure_and_not_run(py_repo: Path) -> None:
    inv = write_locked(py_repo, load_config(py_repo), "inv_00000001", PASS)
    (py_repo / inv.verification.harness_path).write_text(PASS + "\n# tweaked\n")
    report = run(py_repo, [inv])
    assert report.integrity_failures == ["inv_00000001: harness modified since approval"]
    assert report.results == [] and report.failing_ids == ["inv_00000001"]


def test_missing_harness_and_changed_assertion(py_repo: Path) -> None:
    cfg = load_config(py_repo)
    a = write_locked(py_repo, cfg, "inv_00000001", PASS)
    b = write_locked(py_repo, cfg, "inv_00000002", PASS)
    (py_repo / a.verification.harness_path).unlink()
    b = b.model_copy(update={"assertion": "Something else entirely now."})
    problems = run(py_repo, [a, b]).integrity_failures
    assert problems == ["inv_00000001: harness missing (.seamspec/tests/test_inv_00000001.py)",
                        "inv_00000002: assertion modified since approval"]  # fmt: skip


def test_init_records_fingerprints_so_fresh_repos_verify(py_repo: Path) -> None:
    assert json.loads((py_repo / ".seamspec/fingerprints.json").read_text()).keys() == {".seamspec/pytest.ini"}
    assert run(py_repo, []).passed


def test_changed_runner_config_fails_until_confirmed(py_repo: Path) -> None:
    inv = write_locked(py_repo, load_config(py_repo), "inv_00000001", PASS)
    ini = py_repo / ".seamspec/pytest.ini"
    ini.write_text(ini.read_text() + "addopts = -p no:randomly\n")
    report = run(py_repo, [inv])
    assert not report.passed
    assert report.config_failures == [".seamspec/pytest.ini: changed since it was last confirmed in `seamspec review`"]
    confirmed = verifier.current_fingerprints(py_repo, load_config(py_repo))
    assert run(py_repo, [inv], fingerprints=confirmed).passed


def test_proposed_invariants_skip_integrity(py_repo: Path) -> None:
    inv = write_locked(py_repo, load_config(py_repo), "inv_00000001", PASS, status=InvStatus.PROPOSED)
    assert run(py_repo, [inv]).passed


# --- environment -------------------------------------------------------------------------------


def test_env_is_scrubbed_and_has_no_verification_flag(py_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s3cr3t")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k nothing_matches")
    monkeypatch.setenv("DATABASE_URL", "postgres://x")
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    cfg_path = py_repo / ".seamspec/config.toml"
    cfg_path.write_text(cfg_path.read_text().replace("env_passthrough = []", 'env_passthrough = ["DATABASE_URL"]'))
    code = (
        "import os\n\ndef test_env():\n"
        "    assert 'AWS_SECRET_ACCESS_KEY' not in os.environ\n"
        "    assert 'OPENAI_API_KEY' not in os.environ\n"
        "    assert os.environ['DATABASE_URL'] == 'postgres://x'\n"
        "    assert os.environ.get('LC_ALL') == 'C.UTF-8'\n"
        "    assert not [k for k in os.environ if 'SEAMSPEC' in k or 'VERIF' in k]\n"
    )
    inv = write_locked(py_repo, load_config(py_repo), "inv_00000001", code)
    report = run(py_repo, [inv])
    assert report.passed, report.results[0].output


def test_build_env_unit() -> None:
    cfg = parse_config('[execution]\nenv_passthrough = ["DATABASE_URL"]\n')
    env = verifier.build_env(cfg, {"PATH": "/bin", "GITHUB_TOKEN": "x", "DATABASE_URL": "d", "LC_CTYPE": "c"})
    assert env == {"PATH": "/bin", "DATABASE_URL": "d", "LC_CTYPE": "c"}


def test_build_env_puts_project_tools_first(tmp_path: Path) -> None:
    cfg = parse_config("")
    for rel in (".venv/bin", "node_modules/.bin"):
        (tmp_path / rel).mkdir(parents=True)
    env = verifier.build_env(cfg, {"PATH": "/usr/bin"}, root=tmp_path)
    assert env["PATH"].split(os.pathsep) == [
        str(tmp_path / ".venv/bin"),
        str(tmp_path / "node_modules/.bin"),
        "/usr/bin",
    ]
    # an activated virtualenv is the user's choice: .venv / venv stay out of the way
    env = verifier.build_env(cfg, {"PATH": "/usr/bin", "VIRTUAL_ENV": "/elsewhere"}, root=tmp_path)
    assert env["PATH"].split(os.pathsep) == [str(tmp_path / "node_modules/.bin"), "/usr/bin"]
    assert verifier.build_env(cfg, {}, root=tmp_path / "nothing") == {}
    # a runner's own PATH still gets the project's tools in front of it
    env = verifier.build_env(cfg, {"PATH": "/usr/bin"}, root=tmp_path, overrides={"PATH": "/custom/bin"})
    assert env["PATH"].split(os.pathsep)[-1] == "/custom/bin" and str(tmp_path / ".venv/bin") in env["PATH"]


@pytest.mark.skipif(os.name != "posix", reason="shell-script stand-in for a venv")
def test_project_venv_runs_without_activation(py_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hooks and GUI git clients start with a bare PATH: `pytest` still resolves to the project's .venv."""
    venv_bin = py_repo / ".venv/bin"
    venv_bin.mkdir(parents=True)
    script = venv_bin / "pytest"
    script.write_text(f'#!/bin/sh\ntouch "$0.ran"\nexec "{sys.executable}" -m pytest "$@"\n')
    script.chmod(0o755)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    inv = write_locked(py_repo, load_config(py_repo), "inv_00000001", PASS)
    report = run(py_repo, [inv])
    assert report.passed, report.results[0].output
    assert (venv_bin / "pytest.ran").exists()


# --- runner problems, timeouts and the deadline ------------------------------------------------


def _custom_runner(root: Path, cmd: list[str], report: str = "none", timeout: int = 120) -> None:
    """Replace the pytest runner with a small custom one for process-level tests."""
    cfg_path = root / ".seamspec/config.toml"
    text = cfg_path.read_text()
    start = text.index("[runners.pytest]")
    end = text.index("[hooks]")
    custom = (
        "[runners.pytest]\n"
        f"cmd = {json.dumps(cmd)}\n"
        'harness_dir = ".seamspec/tests"\nfilename = "test_{id}.py"\n'
        f'report = "{report}"\n\n'
    )
    text = text[:start] + custom + text[end:]
    text = text.replace("timeout_seconds = 120", f"timeout_seconds = {timeout}")
    cfg_path.write_text(text)


RUN_EACH = "import runpy, sys\nfails = 0\nfor p in sys.argv[1:]:\n    try:\n        runpy.run_path(p)\n    except Exception:\n        fails += 1\nsys.exit(1 if fails else 0)\n"  # noqa: E501


def test_isolated_reruns_attribute_without_a_report(py_repo: Path) -> None:
    (py_repo / ".seamspec/run_each.py").write_text(RUN_EACH)
    _custom_runner(py_repo, [sys.executable, ".seamspec/run_each.py", "{each}"])
    cfg = load_config(py_repo)
    ok = write_locked(py_repo, cfg, "inv_00000001", "x = 1\n")
    bad = write_locked(py_repo, cfg, "inv_00000002", "raise SystemExit(3)\n")
    bad2 = write_locked(py_repo, cfg, "inv_00000003", "raise ValueError('boom')\n")
    report = run(py_repo, [ok, bad, bad2])
    assert report.failing_ids == ["inv_00000002", "inv_00000003"]


def test_missing_runner_binary(py_repo: Path) -> None:
    _custom_runner(py_repo, ["seamspec-no-such-binary", "{each}"])
    inv = write_locked(py_repo, load_config(py_repo), "inv_00000001", "x = 1\n")
    result = run(py_repo, [inv]).results[0]
    assert not result.passed and "not found" in result.output


def test_unknown_runner(py_repo: Path) -> None:
    inv = write_locked(py_repo, load_config(py_repo), "inv_00000001", PASS)
    inv = inv.model_copy(update={"verification": inv.verification.model_copy(update={"runner": "nope"})})
    result = run(py_repo, [inv]).results[0]
    assert not result.passed and "Unknown runner 'nope'" in result.output


SPAWN_AND_HANG = (
    "import subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
    "open('child.pid', 'w').write(str(child.pid))\n"
    "time.sleep(60)\n"
)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX-only in v0.1")
def test_timeout_kills_the_whole_process_group(py_repo: Path) -> None:
    _custom_runner(py_repo, [sys.executable, "{each}"], timeout=2)
    inv = write_locked(py_repo, load_config(py_repo), "inv_00000001", SPAWN_AND_HANG)
    start = time.monotonic()
    result = run(py_repo, [inv]).results[0]
    assert result.timed_out and not result.passed and not result.incomplete
    assert time.monotonic() - start < 20
    pid = int((py_repo / "child.pid").read_text())
    for _ in range(50):
        if not _alive(pid):
            break
        time.sleep(0.1)
    assert not _alive(pid), "grandchild survived the timeout"


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX-only in v0.1")
def test_deadline_cut_is_incomplete_not_a_pass(py_repo: Path) -> None:
    _custom_runner(py_repo, [sys.executable, "{each}"])
    inv = write_locked(py_repo, load_config(py_repo), "inv_00000001", SPAWN_AND_HANG)
    report = run(py_repo, [inv], deadline=time.monotonic() + 2)
    assert report.incomplete and not report.passed
    assert report.failing_ids == []  # not a failure either: an explicit third outcome


def test_deadline_already_reached_runs_nothing(py_repo: Path) -> None:
    inv = write_locked(py_repo, load_config(py_repo), "inv_00000001", PASS)
    report = run(py_repo, [inv], deadline=time.monotonic() - 1)
    assert report.incomplete and "deadline reached" in report.results[0].output


def test_save_last(py_repo: Path) -> None:
    inv = write_locked(py_repo, load_config(py_repo), "inv_00000001", FAIL)
    report = run(py_repo, [inv])
    verifier.save_last(py_repo, report)
    data = json.loads((py_repo / ".seamspec/.local/last_verify.json").read_text())
    assert data["passed"] is False and data["failing_ids"] == ["inv_00000001"] and data["at"].endswith("Z")


# --- pure helpers --------------------------------------------------------------------------------


def test_expand_argv() -> None:
    runner = RunnerCfg(
        cmd=["go", "test", "-json", "--out={report}", "{each}"],
        harness_dir="internal/seamspec",
        filename="{id}/seamspec_test.go",
        each=["{dir}", "{dir}"],
    )
    from .conftest import make_invariant

    invs = [make_invariant("inv_00000001"), make_invariant("inv_00000002")]
    invs = [
        i.model_copy(
            update={"verification": i.verification.model_copy(update={"harness_path": runner.harness_path(i.id)})}
        )  # noqa: E501
        for i in invs
    ]
    argv = verifier.expand_argv(runner, invs, Path("/r/report.xml"))
    assert argv == ["go", "test", "-json", "--out=/r/report.xml",
                    "./internal/seamspec/inv_00000001", "./internal/seamspec/inv_00000001",
                    "./internal/seamspec/inv_00000002", "./internal/seamspec/inv_00000002"]  # fmt: skip


def test_truncate_keeps_head_and_tail() -> None:
    text = "H" * 3000 + "T" * 3000
    out = verifier._truncate(text, 400)
    assert out.startswith("H" * 100) and out.endswith("T" * 300) and "truncated 5600 chars" in out


def test_junit_parser(tmp_path: Path) -> None:
    xml = tmp_path / "r.xml"
    xml.write_text(
        "<testsuites><testsuite>"
        '<testcase classname="t.test_inv_00000001" name="a"/>'
        '<testcase classname="t.test_inv_00000002" name="b"><failure/></testcase>'
        '<testcase classname="" name="t.test_inv_00000003"><error/></testcase>'
        '<testcase classname="t.test_inv_00000004" name="c"><skipped/></testcase>'
        "</testsuite></testsuites>"
    )
    ids = [f"inv_0000000{n}" for n in range(1, 6)]
    failed, empty = reports.junit(xml, ids)
    assert failed == {"inv_00000002", "inv_00000003"}
    assert empty == {"inv_00000004", "inv_00000005"}
    assert reports.junit(tmp_path / "missing.xml", ids) is None
    (tmp_path / "bad.xml").write_text("<not xml")
    assert reports.junit(tmp_path / "bad.xml", ids) is None


def test_go_test_json_parser() -> None:
    events = [
        {"Action": "run", "Package": "m/internal/seamspec/inv_00000001", "Test": "TestA"},
        {"Action": "pass", "Package": "m/internal/seamspec/inv_00000001", "Test": "TestA"},
        {"Action": "output", "Package": "m/internal/seamspec/inv_00000002", "Output": "boom\n"},
        {"Action": "fail", "Package": "m/internal/seamspec/inv_00000002", "Test": "TestB"},
        {"Action": "skip", "Package": "m/internal/seamspec/inv_00000003", "Test": "TestC"},
    ]
    stdout = "\n".join(json.dumps(e) for e in events) + "\n# build noise\n"
    ids = ["inv_00000001", "inv_00000002", "inv_00000003"]
    attributed, text = reports.go_test_json(stdout, ids)
    assert attributed == ({"inv_00000002"}, {"inv_00000003"})
    assert "boom" in text and "# build noise" in text
    assert reports.go_test_json("not json at all", ids)[0] is None


# --- what failed, for the summary (dogfooding #11, ADR-20261013-4e9b) -------------------------------

PARAM = (
    "import pytest\nfrom src.queue import backoff_delay\n\n\n"
    '@pytest.mark.parametrize("n", [50, 100, 200])\ndef test_cap(n):\n    assert backoff_delay(n) <= 30\n'
)


def test_junit_checks_reads_line_and_message_and_counts_repeats(tmp_path: Path) -> None:
    xml = tmp_path / "r.xml"
    trace = (
        "def test_cap(n):\n&gt;   assert f(n) == 5\nE   assert 4 == 5\n\n"
        ".seamspec/tests/test_inv_00000001.py:29: AssertionError"
    )
    case = '<testcase classname="t.test_inv_00000001" name="a[{n}]">'
    one = case + '<failure message="assert 4 == 5&#10; + where 4 = f({n})">'
    xml.write_text(
        "<testsuites><testsuite>"
        f"{one.format(n=1)}{trace}</failure></testcase>"
        f"{one.format(n=2)}{trace}</failure></testcase>"
        '<testcase classname="" name="t.test_inv_00000002"><error message="collection failure">'
        "ImportError while importing test module\n.seamspec/tests/test_inv_00000002.py:1: in &lt;module&gt;\n"
        "    from src.queue import x\nE   ImportError: cannot import name 'x'</error></testcase>"
        '<testcase classname="tests/seamspec/inv_00000003.test.ts" name="cap"><failure message="expected 9 to be 3">'
        "AssertionError: expected 9 to be 3\n ❯ helper tests/seamspec/inv_00000003.test.ts:3:40\n"
        " ❯ tests/seamspec/inv_00000003.test.ts:9:1</failure></testcase>"
        '<testcase classname="t.test_inv_00000004" name="ok"/>'
        "</testsuite></testsuites>"
    )
    ids = [f"inv_0000000{n}" for n in range(1, 5)]
    checks = reports.junit_checks(xml, ids)
    assert checks == {
        "inv_00000001": [reports.FailedCheck(29, "assert 4 == 5", 2)],  # two cases, one line
        "inv_00000002": [reports.FailedCheck(1, "ImportError: cannot import name 'x'")],
        "inv_00000003": [reports.FailedCheck(3, "expected 9 to be 3")],  # a JavaScript stack starts at the failure
    }
    assert reports.junit_checks(tmp_path / "missing.xml", ids) == {}
    (tmp_path / "bad.xml").write_text("<not xml")
    assert reports.junit_checks(tmp_path / "bad.xml", ids) == {}


def test_failure_summary_names_the_rule_and_the_check(py_repo: Path) -> None:
    from seamspec.core import failtext
    from seamspec.core.store import Store

    cfg = load_config(py_repo)
    a = write_locked(py_repo, cfg, "inv_00000001", PARAM)
    b = write_locked(py_repo, cfg, "inv_00000002", PASS)
    assert run(py_repo, [a, b]).results[0].checks == {}  # nothing recorded for a passing run
    (py_repo / "src/queue.py").write_text("def backoff_delay(n):\n    return 99.0\n")
    report = run(py_repo, [a, b])
    lines, unexplained = failtext.summary(Store(py_repo), report)
    assert unexplained == [] and failtext.count(report) == "2 rules fail"
    assert lines == [
        "  inv_00000001 · Rule inv_00000001",
        "    line 7: assert backoff_delay(n) <= 30",
        "      assert 99.0 <= 30  (3 test cases)",
        "    Test: .seamspec/tests/test_inv_00000001.py",
        "",
        "  inv_00000002 · Rule inv_00000002",
        "    line 4: assert backoff_delay(100) <= 30",
        "      assert 99.0 <= 30",
        "    Test: .seamspec/tests/test_inv_00000002.py",
    ]
    assert report.to_dict()["results"][0]["checks"]["inv_00000002"] == [
        {"line": 4, "message": "assert 99.0 <= 30", "cases": 1}
    ]


def test_failure_summary_never_hides_what_it_cannot_explain(py_repo: Path) -> None:
    """A timeout, a tampered test, a test that ran nothing: each is listed with its reason, and a
    result with no report keeps its raw output."""
    from seamspec.core import failtext
    from seamspec.core.store import Store

    cfg = load_config(py_repo)
    empty = write_locked(py_repo, cfg, "inv_00000001", "def helper():\n    pass\n")
    tampered = write_locked(py_repo, cfg, "inv_00000002", PASS)
    (py_repo / tampered.verification.harness_path).write_text(PASS + "# edited\n")
    report = run(py_repo, [empty, tampered])
    lines, unexplained = failtext.summary(Store(py_repo), report)
    assert "  inv_00000002 · Rule inv_00000002" in lines and "    harness modified since approval" in lines
    assert "    ran no tests, or skipped every test (counts as a failure)" in lines and unexplained == []

    _custom_runner(py_repo, [sys.executable, "-c", "import sys; sys.exit(3)"], report="none")
    cfg = load_config(py_repo)
    one, two = (write_locked(py_repo, cfg, f"inv_0000000{n}", PASS) for n in (3, 4))
    report = run(py_repo, [one, two])
    lines, unexplained = failtext.summary(Store(py_repo), report)
    assert len(unexplained) == 1 and failtext.raw(unexplained[0]).startswith("[FAIL] ")
    assert any("the runner's report doesn't say" in ln for ln in lines)
