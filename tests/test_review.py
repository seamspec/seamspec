"""`seamspec review` and the red-green check (SPEC §11.3, §11.4, §15)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from seamspec.cli import app
from seamspec.core import lifecycle, redgreen, requests
from seamspec.core.config import load_config
from seamspec.core.models import InvStatus
from seamspec.core.store import Store

from .conftest import git
from .test_lifecycle import PASS, propose

runner = CliRunner()

JITTER_CODE = "def backoff_delay(n):\n    return min(0.1 * 2 ** n, 30.0)\n\n\ndef jitter(x):\n    return x / 2\n"
JITTER_TEST = "from src.queue import jitter\n\n\ndef test_jitter_halves():\n    assert jitter(10) == 5\n"


@pytest.fixture
def human(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")


@pytest.fixture
def in_repo(git_repo: Path, monkeypatch: pytest.MonkeyPatch, human: None) -> Path:
    monkeypatch.chdir(git_repo)
    return git_repo


def check(root: Path, inv_id: str) -> redgreen.RedGreen:
    store = Store(root)
    return redgreen.check(store, load_config(root), store.get(inv_id))


def worktrees(root: Path) -> int:
    return git(root, "worktree", "list").count("\n")


# --- red-green -------------------------------------------------------------------------------------


def test_new_behavior_fails_on_head(git_repo: Path) -> None:
    (git_repo / "src/queue.py").write_text(JITTER_CODE)  # uncommitted change
    inv_id = propose(git_repo, code=JITTER_TEST, assertion="Jitter halves the delay.")["id"]
    result = check(git_repo, inv_id)
    assert result.verdict == "yes", result.detail
    assert worktrees(git_repo) == 1, "temporary worktree was not removed"
    assert not list((git_repo / ".seamspec/tests").glob("test_inv_*.py")), "proposed test left in place"


def test_existing_behavior_passes_on_head(git_repo: Path) -> None:
    inv_id = propose(git_repo)["id"]  # the 30s cap is already committed
    result = check(git_repo, inv_id)
    assert result.verdict == "no" and "already existed" in result.detail
    assert worktrees(git_repo) == 1


def test_not_applicable_cases(git_repo: Path, py_repo_factory=None) -> None:
    failing = propose(git_repo, code="def test_x():\n    assert False\n")["id"]
    assert check(git_repo, failing).verdict == "n/a"
    assert "fails on your working tree" in check(git_repo, failing).detail


def test_no_git_or_no_commits(py_repo: Path) -> None:
    inv_id = propose(py_repo)["id"]
    assert check(py_repo, inv_id).detail.startswith("not a git repository")
    git(py_repo, "init", "-q")
    assert check(py_repo, inv_id).detail.startswith("no commits yet")


def test_seamspec_in_a_subfolder(tmp_path: Path) -> None:
    from seamspec.installers import scaffold

    sub = tmp_path / "services/api"
    (sub / "src").mkdir(parents=True)
    (sub / "pyproject.toml").write_text("")
    (sub / "src/__init__.py").write_text("")
    (sub / "src/queue.py").write_text("def backoff_delay(n):\n    return min(0.1 * 2 ** n, 30.0)\n")
    git(tmp_path, "init", "-q", "-b", "main")
    scaffold.init(sub, auto_run=True, actor="t")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "init")
    (sub / "src/queue.py").write_text(JITTER_CODE)
    inv_id = propose(sub, code=JITTER_TEST, assertion="Jitter halves the delay.")["id"]
    assert check(sub, inv_id).verdict == "yes"


# --- the review flow ---------------------------------------------------------------------------------


def test_nothing_to_review(in_repo: Path) -> None:
    out = runner.invoke(app, ["review"])
    assert out.exit_code == 0 and "Nothing to review." in out.output


def test_review_refuses_without_a_terminal(git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(git_repo)
    out = runner.invoke(app, ["review"])
    assert out.exit_code == 1 and "interactive terminal" in out.output


def test_approve_and_reject_in_one_pass(in_repo: Path) -> None:
    (in_repo / "src/queue.py").write_text(JITTER_CODE)
    good = propose(in_repo, code=JITTER_TEST, assertion="Jitter halves the delay.")["id"]
    weak = propose(in_repo)["id"]  # passes on HEAD: the reviewer should see "no"
    # good: run red-green (enter), approve; weak: run red-green (enter), reject with reason, dead end yes
    out = runner.invoke(app, ["review"], input="\na\n\nr\nonly restates old behavior\ny\n")
    assert out.exit_code == 0, out.output
    assert "fails without your change: yes" in out.output
    assert "fails without your change: no" in out.output
    assert "| from src.queue import jitter" in out.output  # the full test is shown before the prompt
    assert out.output.index("| from src.queue import jitter") < out.output.index("[a]pprove")
    store = Store(in_repo)
    assert store.get(good).status == InvStatus.LOCKED
    assert store.get(weak).status == InvStatus.REJECTED
    assert "approved 1, rejected 1" in out.output and "Commit the .seamspec/ changes" in out.output


def test_skip_red_green_skip_and_quit(in_repo: Path) -> None:
    a = propose(in_repo)["id"]
    b = propose(in_repo)["id"]
    out = runner.invoke(app, ["review"], input="n\ns\nn\nq\n")
    assert out.exit_code == 0 and "Stopped." in out.output
    assert "fails without your change: " not in out.output  # the check itself never ran
    assert {Store(in_repo).get(i).status for i in (a, b)} == {InvStatus.PROPOSED}


def test_unconfirmed_runner_config_blocks_approval(in_repo: Path) -> None:
    ini = in_repo / ".seamspec/pytest.ini"
    ini.write_text(ini.read_text() + "# tweak\n")
    inv_id = propose(in_repo)["id"]
    out = runner.invoke(app, ["review"], input="n\nn\na\n")  # don't confirm config, skip red-green, try approve
    assert "| # tweak" in out.output and "can't approve while runner config changes are unconfirmed" in out.output
    assert Store(in_repo).get(inv_id).status == InvStatus.PROPOSED
    out = runner.invoke(app, ["review"], input="y\nn\na\n")
    assert "confirmed." in out.output and Store(in_repo).get(inv_id).status == InvStatus.LOCKED


def test_new_dead_ends_first_then_only_once(in_repo: Path) -> None:
    store, cfg = Store(in_repo), load_config(in_repo)
    keep = lifecycle.log_dead_end(
        store, cfg, scope_paths=["src/**"], approach="global retry counter", failure_symptom="herd"
    )
    wrong = lifecycle.log_dead_end(
        store, cfg, scope_paths=["src/**"], approach="sqlite WAL mode", failure_symptom="flaky"
    )
    propose(in_repo)
    shown = sorted((store.get(x["id"]) for x in (keep, wrong)), key=lambda d: (d.created_at, d.id))
    answers = {keep["id"]: "k\n", wrong["id"]: "w\nlibrary fixed it\n"}
    out = runner.invoke(app, ["review"], input="".join(answers[d.id] for d in shown) + "n\ns\n")
    assert out.output.index("Dead ends recorded since your last review") < out.output.index("Proposed rules")
    assert store.get(keep["id"]).status == "ACTIVE" and store.get(wrong["id"]).status == "RETIRED"
    again = runner.invoke(app, ["review"], input="n\ns\n")
    assert "Dead ends recorded" not in again.output


def test_supersede_requests(in_repo: Path) -> None:
    store, cfg = Store(in_repo), load_config(in_repo)
    a, b = propose(in_repo)["id"], propose(in_repo)["id"]
    lifecycle.approve(store, cfg, a)
    lifecycle.approve(store, cfg, b)
    a, b = sorted((a, b))  # requests are listed in id order
    lifecycle.request_supersede(store, a, "batch jobs need 60s")
    lifecycle.request_supersede(store, b, "agent got confused")
    out = runner.invoke(app, ["review"], input="a\nd\n")
    assert out.exit_code == 0, out.output
    assert store.get(a).status == InvStatus.SUPERSEDED
    assert store.get(b).status == InvStatus.LOCKED and requests.pending_supersede_ids(store) == set()
    assert "declined 1" in out.output


def test_bad_key_is_asked_again(in_repo: Path) -> None:
    inv_id = propose(in_repo)["id"]
    out = runner.invoke(app, ["review"], input="n\nx\ns\n")
    assert "please answer one of: a, r, s, q" in out.output
    assert Store(in_repo).get(inv_id).status == InvStatus.PROPOSED


# --- seamspec approve with changed runner config ----------------------------------------------------


def test_cli_approve_asks_about_changed_config(in_repo: Path) -> None:
    ini = in_repo / ".seamspec/pytest.ini"
    ini.write_text(ini.read_text() + "# tweak\n")
    inv_id = propose(in_repo, code=PASS)["id"]
    declined = runner.invoke(app, ["approve", inv_id], input="n\n")
    assert declined.exit_code == 1 and "| # tweak" in declined.output
    assert Store(in_repo).get(inv_id).status == InvStatus.PROPOSED
    accepted = runner.invoke(app, ["approve", inv_id], input="y\ny\n")
    assert accepted.exit_code == 0 and Store(in_repo).get(inv_id).status == InvStatus.LOCKED
    prints = json.loads((in_repo / ".seamspec/fingerprints.json").read_text())
    assert prints  # confirmed together with the approval


# --- regressions from Copilot's review of #14 -------------------------------------------------------


def test_red_green_real_failure_mentioning_not_found_is_yes(git_repo: Path) -> None:
    """Finding 3: a real assertion failure whose output says "not found" is not "couldn't run"."""
    (git_repo / "src/queue.py").write_text(JITTER_CODE + "\n\ndef lookup(k):\n    return 'found'\n")
    code = (
        "from src import queue\n\n\ndef test_lookup():\n"
        "    assert getattr(queue, 'lookup', lambda k: 'not found')('x') == 'found'\n"
    )
    inv_id = propose(git_repo, code=code, assertion="Lookup finds existing keys.")["id"]
    assert check(git_repo, inv_id).verdict == "yes"


def test_red_green_filesystem_error_is_not_applicable(git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Finding 4: preparing the HEAD copy can fail (e.g. no symlinks on Windows); review must go on."""

    def boom(*args, **kwargs):
        raise PermissionError("symlinks not allowed")

    monkeypatch.setattr(redgreen, "_prepare", boom)
    inv_id = propose(git_repo)["id"]
    result = check(git_repo, inv_id)
    assert result.verdict == "n/a" and "couldn't prepare the HEAD copy" in result.detail
    assert worktrees(git_repo) == 1


def test_supersede_requests_oldest_first(in_repo: Path) -> None:
    """Finding 5: requests are shown by request time, not by (random) id."""
    store, cfg = Store(in_repo), load_config(in_repo)
    a, b = sorted((propose(in_repo)["id"], propose(in_repo)["id"]))
    lifecycle.approve(store, cfg, a)
    lifecycle.approve(store, cfg, b)
    requests.save(store, requests.SupersedeRequest(b, "older request", None, "2026-10-01T00:00:00Z"))
    requests.save(store, requests.SupersedeRequest(a, "newer request", None, "2026-10-02T00:00:00Z"))
    out = runner.invoke(app, ["review"], input="s\nq\n")
    assert out.output.index("older request") < out.output.index("newer request")


def test_quitting_keeps_unreviewed_dead_ends_new(in_repo: Path) -> None:
    """Finding 6: `q` must leave the dead ends you didn't reach in the next review."""
    store, cfg = Store(in_repo), load_config(in_repo)
    first = lifecycle.log_dead_end(store, cfg, scope_paths=["src/**"], approach="first approach", failure_symptom="x")
    second = lifecycle.log_dead_end(store, cfg, scope_paths=["src/**"], approach="second approach", failure_symptom="y")
    order = sorted((store.get(i["id"]) for i in (first, second)), key=lambda d: (d.created_at, d.id))
    runner.invoke(app, ["review"], input="k\nq\n")  # answer the first, quit on the second
    again = runner.invoke(app, ["review"], input="k\n")
    assert order[1].approach in again.output and order[0].approach not in again.output


def test_config_changed_while_being_reviewed_is_not_confirmed(in_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Findings 1-2: confirmation is bound to the bytes that were displayed."""
    from seamspec import review as review_mod

    ini = in_repo / ".seamspec/pytest.ini"
    ini.write_text(ini.read_text() + "# shown tweak\n")
    original = review_mod.show_config_changes

    def show_then_tamper(store, cfg):
        shown = original(store, cfg)
        ini.write_text(ini.read_text() + "# sneaky edit after display\n")
        return shown

    monkeypatch.setattr(review_mod, "show_config_changes", show_then_tamper)
    propose(in_repo)
    out = runner.invoke(app, ["review"], input="y\nn\na\n")
    assert "changed again while you were reviewing" in out.output
    assert "can't approve while runner config changes are unconfirmed" in out.output
