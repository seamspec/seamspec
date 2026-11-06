"""A test that stops with an error isn't told to "Fix the regression" (ADR-20261105-0576).

SessionWalk dogfooding: a rule's test that couldn't even import was reported with the same advice as a
check that failed, "Fix the regression, or supersede the rule", which points an agent at the wrong fix
(or at retiring a rule over a setup problem). pytest tells the two apart (<error> vs <failure>), and
so does SeamSpec now.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from seamspec.adapters import claude
from seamspec.cli import app
from seamspec.core import failtext
from seamspec.core.reports import FailedCheck
from seamspec.core.verifier import RunnerResult, VerifyReport

from .test_claude_adapter import BROKEN_CODE, lock, stop

runner = CliRunner()


@pytest.fixture
def human(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")


def result(ids: list[str], *checks: FailedCheck, **kw) -> RunnerResult:
    return RunnerResult("pytest", ids, passed=False, output="", duration_s=0.1, checks={ids[0]: list(checks)}, **kw)


ERROR = FailedCheck(1, "ModuleNotFoundError: No module named 'src.queue'", errored=True)
FAILURE = FailedCheck(4, "assert 99.0 <= 30")


@pytest.mark.parametrize(
    "report,expected",
    [
        (VerifyReport(False, results=[result(["inv_1"], ERROR)]), True),
        (VerifyReport(False, results=[RunnerResult("jest", ["inv_1"], False, "", 0.0, could_not_run=True)]), True),
        (VerifyReport(False, results=[result(["inv_1"], FAILURE)]), False),
        (VerifyReport(False, results=[result(["inv_1"], ERROR, FAILURE)]), False),  # one check failed: a regression
        (VerifyReport(False, results=[result(["inv_1"], ERROR), result(["inv_2"], FAILURE)]), False),
        (VerifyReport(False, results=[result(["inv_1"], ERROR, timed_out=True)]), False),  # a hang can be a regression
        # Copilot on #113: the Stop deadline marks a timed-out group incomplete too; it still rules this out
        (
            VerifyReport(False, results=[result(["inv_1"], ERROR), result(["inv_2"], timed_out=True, incomplete=True)]),
            False,
        ),
        (VerifyReport(False, results=[result(["inv_1"])]), False),  # nothing says what failed: assume the worst
        (VerifyReport(False, integrity_failures=["inv_1: harness modified since approval"]), False),
        (VerifyReport(False, config_failures=["pytest.ini changed"], results=[result(["inv_1"], ERROR)]), False),
    ],
)
def test_did_not_start_only_when_no_check_failed(report: VerifyReport, expected: bool) -> None:
    assert failtext.did_not_start(report) is expected


def test_verify_says_the_test_did_not_start(git_repo: Path, monkeypatch: pytest.MonkeyPatch, human: None) -> None:
    inv_id = lock(git_repo)
    (git_repo / "src/queue.py").unlink()  # the test can't import what it checks
    monkeypatch.chdir(git_repo)
    out = runner.invoke(app, ["verify", "--all"])
    assert out.exit_code == 1
    assert failtext.NOT_STARTED_HINT in out.output and "Fix the regression" not in out.output
    assert f"{inv_id} ·" in out.output and "(an error, not a failed check)" in out.output


def test_verify_still_says_fix_the_regression_for_a_failed_check(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, human: None
) -> None:
    lock(git_repo)
    (git_repo / "src/queue.py").write_text(BROKEN_CODE)
    monkeypatch.chdir(git_repo)
    out = runner.invoke(app, ["verify", "--all"])
    assert out.exit_code == 1
    assert failtext.REGRESSION_HINT in out.output and failtext.NOT_STARTED_HINT not in out.output
    assert "(an error, not a failed check)" not in out.output


def test_the_stop_hook_tells_the_agent_not_to_supersede_over_it(git_repo: Path, human: None) -> None:
    lock(git_repo)
    (git_repo / "src/queue.py").unlink()
    out = stop(git_repo)
    assert out is not None and out["decision"] == "block"
    assert claude.NOT_STARTED_HINT in out["reason"] and claude.SUPERSEDE_HINT not in out["reason"]


def test_the_stop_hook_keeps_the_supersede_hint_for_a_regression(git_repo: Path, human: None) -> None:
    lock(git_repo)
    (git_repo / "src/queue.py").write_text(BROKEN_CODE)
    out = stop(git_repo)
    assert out is not None and claude.SUPERSEDE_HINT in out["reason"] and claude.NOT_STARTED_HINT not in out["reason"]


def test_an_error_on_a_declined_rule_gets_the_error_advice(git_repo: Path, human: None) -> None:
    """Copilot on #113: a person declined retiring the rule earlier; now its test can't import. The decline is
    still shown, but the advice is about the error, not "Fix the regression"."""
    from seamspec.core import lifecycle, requests
    from seamspec.core.store import Store

    inv_id = lock(git_repo)
    store = Store(git_repo)
    lifecycle.request_supersede(store, inv_id, "cap is changing")
    requests.decline(store, inv_id, "we keep the 30 s cap")
    (git_repo / "src/queue.py").unlink()
    out = stop(git_repo)
    assert out is not None and f"A person declined the request to retire {inv_id}" in out["reason"]
    assert claude.NOT_STARTED_HINT in out["reason"] and claude.DECLINED_HINT not in out["reason"]
