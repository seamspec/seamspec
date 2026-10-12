"""`seamspec review` and the red-green check (SPEC §11.3, §11.4, §15)."""

from __future__ import annotations

import json
import os
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
    # Dogfooding #9: HEAD has no `jitter` to import, so any test of it fails there. Say so.
    assert result.new_code and "ImportError: cannot import name 'jitter'" in result.detail
    assert result.line().startswith("Fails without your change: YES, BUT ONLY BECAUSE THE CODE IS NEW (the last commit")
    assert f"`seamspec verify --proposed {inv_id}`" in (result.hint() or "")
    assert worktrees(git_repo) == 1, "temporary worktree was not removed"
    assert not list((git_repo / ".seamspec/tests").glob("test_inv_*.py")), "proposed test left in place"


def test_changed_behavior_is_a_plain_yes_that_shows_what_failed_on_head(git_repo: Path) -> None:
    """The code exists on HEAD and behaves differently there: the strong kind of "yes"."""
    (git_repo / "src/queue.py").write_text("def backoff_delay(n):\n    return min(0.1 * 2 ** n, 60.0)\n")
    code = "from src.queue import backoff_delay\n\n\ndef test_cap():\n    assert backoff_delay(100) == 60\n"
    inv_id = propose(git_repo, code=code, assertion="Retry delay is capped at 60 seconds.")["id"]
    result = check(git_repo, inv_id)
    assert result.verdict == "yes" and not result.new_code and result.hint() is None
    assert result.line() == (
        "Fails without your change: YES (it fails on HEAD and passes with your change; on HEAD: assert 30.0 == 60)"
    )


@pytest.mark.parametrize(
    "message,missing",
    [
        ("ModuleNotFoundError: No module named 'specagent.phase0.draft'", True),
        ("ImportError: cannot import name 'jitter' from 'src.queue'", True),
        ("AttributeError: module 'src.queue' has no attribute 'jitter'", True),
        ("FileNotFoundError: config/policy.yaml not found above this test", True),
        ("(0 , jitter) is not a function", True),
        ('Error: Failed to resolve import "../../src/new" from "tests/seamspec/inv_1.test.ts"', True),
        ("assert 4 == 5", False),
        ("AssertionError: assert 'not found' == 'found'", False),
        ("AttributeError: 'NoneType' object has no attribute 'id'", False),  # the code ran and gave a wrong value
        ("AttributeError: type object 'Gateway' has no attribute 'retry'", True),
        ("TypeError: unsupported operand type(s) for +: 'int' and 'str'", False),
        ("expected 9 to be less than or equal to 3", False),
    ],
)
def test_missing_code_messages(message: str, missing: bool) -> None:
    assert bool(redgreen.MISSING_CODE.search(message)) is missing


def test_review_prints_the_hint_for_new_code(in_repo: Path) -> None:
    (in_repo / "src/queue.py").write_text(JITTER_CODE)
    inv_id = propose(in_repo, code=JITTER_TEST, assertion="Jitter halves the delay.")["id"]
    out = runner.invoke(app, ["review"], input="y\ns\n")
    assert "YES, BUT ONLY BECAUSE THE CODE IS NEW" in out.output
    assert (
        f"To see this test catch something: break the new code on purpose, run `seamspec verify --proposed {inv_id}`"
        in out.output
    )


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


# --- red-green with an editable install (dogfooding finding #4, ADR-20261011-3c7e) -------------------

WIDGET_TEST = "from widgets.new import triple\n\n\ndef test_triple():\n    assert triple(2) == 6\n"


@pytest.fixture
def editable_repo(git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A package the interpreter imports from an absolute path inside the repository, as an editable
    install does (`uv sync`, `pip install -e`). PYTHONPATH stands in for the virtualenv's `.pth` line:
    both put that folder on sys.path at start-up. The new module is not committed."""
    (git_repo / "lib/widgets").mkdir(parents=True)
    (git_repo / "lib/widgets/__init__.py").write_text("")
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-q", "-m", "widgets package")
    (git_repo / "lib/widgets/new.py").write_text("def triple(n):\n    return n * 3\n")
    monkeypatch.setenv("PYTHONPATH", str(git_repo / "lib"))
    return git_repo


def fake_editable_install(root: Path, line: str) -> Path:
    """What an installer leaves in the project's virtualenv: a `.pth` file in site-packages."""
    site = root / ".venv/lib/python3.12/site-packages"
    site.mkdir(parents=True, exist_ok=True)
    (site / "_widgets.pth").write_text(line + "\n")
    return site


def test_editable_install_no_longer_hides_new_code(editable_repo: Path) -> None:
    """Before the fix this said "no": the HEAD copy imported the working tree's widgets/new.py."""
    fake_editable_install(editable_repo, str(editable_repo / "lib"))
    inv_id = propose(editable_repo, code=WIDGET_TEST, assertion="triple(n) returns three times n.")["id"]
    result = check(editable_repo, inv_id)
    assert result.verdict == "yes", result.detail
    assert worktrees(editable_repo) == 1


def test_existing_code_in_an_editable_install_still_says_no(editable_repo: Path) -> None:
    git(editable_repo, "add", "-A")
    git(editable_repo, "commit", "-q", "-m", "triple")
    inv_id = propose(editable_repo, code=WIDGET_TEST, assertion="triple(n) returns three times n.")["id"]
    assert check(editable_repo, inv_id).verdict == "no"


def test_no_guess_when_the_runner_cant_be_redirected(editable_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A runner that isn't started from a Python script (a binary, a Windows launcher) can't be
    pointed at HEAD's code. With an editable install present, the honest answer is "n/a"."""
    fake_editable_install(editable_repo, str(editable_repo / "lib"))
    monkeypatch.setattr(redgreen, "_shim_runner", lambda *args: False)
    inv_id = propose(editable_repo, code=WIDGET_TEST, assertion="triple(n) returns three times n.")["id"]
    result = check(editable_repo, inv_id)
    assert result.verdict == "n/a" and "editable mode" in result.detail


def test_the_head_run_sets_no_new_environment_variable(editable_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The redirect rides on PATH only (locked rule inv_4b4f5ea7, SPEC 12.4.7)."""
    from seamspec.core import verifier

    seen: list[dict[str, str]] = []
    real = verifier.build_env

    def spy(*args, **kwargs):
        env = real(*args, **kwargs)
        seen.append(env)
        return env

    monkeypatch.setattr(verifier, "build_env", spy)
    inv_id = propose(editable_repo, code=WIDGET_TEST, assertion="triple(n) returns three times n.")["id"]
    assert check(editable_repo, inv_id).verdict == "yes"
    allowed = verifier.BASE_ENV_KEYS
    assert seen and all(set(env) <= allowed or all(k.startswith("LC_") for k in set(env) - allowed) for env in seen)
    assert not [k for env in seen for k in env if "SEAMSPEC" in k.upper()]


@pytest.mark.parametrize(
    ("script", "at"),
    [
        ("#!/proj/.venv/bin/python\n# -*- coding: utf-8 -*-\nimport sys\n", 1),
        ("#!/bin/sh\n'''exec' \"/a long path/python\" \"$0\" \"$@\"\n' '''\nimport sys\n", 3),
        ("#!/proj/.venv/bin/python\nfrom __future__ import annotations\n", None),
        ("#!/proj/.venv/bin/python\n" + "# comment\n" * 40 + '"""Doc."""\nfrom __future__ import annotations\n', None),
        ('#!/bin/sh\nexec pytest "$@"\n', None),
        ("\x7fELF binary", None),
        ("", None),
    ],
)
def test_where_the_redirect_goes_in_a_start_script(script: str, at: int | None) -> None:
    assert redgreen._insert_at(script.splitlines(keepends=True)) == at


def test_import_hook_editable_installs_are_redirected_too(tmp_path: Path) -> None:
    """Copilot, #47: setuptools-style editable installs keep their paths in an `__editable__` module's
    MAPPING and NAMESPACES tables, not on sys.path. Run a copied start script for real and check that
    both tables, and sys.path, end up pointing into the HEAD worktree."""
    import subprocess
    import sys

    repo, wt, shims, site = tmp_path / "repo", tmp_path / "wt", tmp_path / "shims", tmp_path / "site"
    for d in (repo / "src/demo", repo / "ns/part", wt, site):
        d.mkdir(parents=True)
    # What the virtualenv's `.pth` line does at start-up: load the import hook's module.
    mapping, namespaces = {"demo": str(repo / "src/demo")}, {"ns": [str(repo / "ns"), "/elsewhere/ns"]}
    (site / "__editable___demo_finder.py").write_text(f"MAPPING = {mapping!r}\nNAMESPACES = {namespaces!r}\n")
    (site / "sitecustomize.py").write_text("import __editable___demo_finder\n")
    script = tmp_path / "runner"
    script.write_text(
        f"#!{sys.executable}\nimport json, sys\n"
        "hook = sys.modules['__editable___demo_finder']\n"
        "print(json.dumps({'mapping': hook.MAPPING, 'namespaces': hook.NAMESPACES, 'path': sys.path}))\n"
    )
    assert redgreen.write_shim(script, shims, repo, wt)

    env = {"PYTHONPATH": f"{site}{os.pathsep}{repo / 'src'}", "PATH": os.environ.get("PATH", "")}
    out = subprocess.run([str(shims / "runner")], capture_output=True, text=True, env=env, check=True)
    seen = json.loads(out.stdout)
    real_wt = os.path.realpath(wt)
    assert seen["mapping"] == {"demo": f"{real_wt}/src/demo"}
    assert seen["namespaces"] == {"ns": [f"{real_wt}/ns", "/elsewhere/ns"]}  # outside the repo: untouched
    assert f"{real_wt}/src" in seen["path"] and os.path.realpath(repo / "src") not in seen["path"]
    assert str(site) in seen["path"]  # not inside the repository: left alone
    assert (shims / redgreen.APPLIED).exists()


def test_a_start_script_that_would_not_compile_is_not_copied(tmp_path: Path) -> None:
    """A copy that can't start would look like a failing test, i.e. a false "yes"."""
    import sys

    script = tmp_path / "runner"
    script.write_text(f"#!{sys.executable}\ndef broken(:\n")
    assert not redgreen.write_shim(script, tmp_path / "shims", tmp_path, tmp_path / "wt")
    assert not (tmp_path / "shims" / "runner").exists()


def test_the_runner_is_found_the_way_the_verifier_finds_it(git_repo: Path, tmp_path_factory) -> None:
    """Copilot, #47: a runner with its own PATH must get *its* start script copied, not a same-named
    one from the surrounding PATH."""
    import sys

    own = tmp_path_factory.mktemp("own-tools")
    (own / "pytest").write_text(f"#!{sys.executable}\n# THE RUNNER'S OWN PYTEST\nimport sys\n")
    (own / "pytest").chmod(0o755)
    cfg_path = git_repo / ".seamspec/config.toml"
    cfg_path.write_text(
        cfg_path.read_text().replace('report = "junit"', f'report = "junit"\nenv = {{ PATH = "{own}" }}', 1)
    )
    cfg = load_config(git_repo)
    assert cfg.runners["pytest"].env == {"PATH": str(own)}
    shims = tmp_path_factory.mktemp("shims")
    assert redgreen._shim_runner(cfg, "pytest", git_repo, shims, git_repo, git_repo)
    assert "THE RUNNER'S OWN PYTEST" in (shims / "pytest").read_text()


def test_a_copied_runner_that_never_started_is_not_trusted(
    editable_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the copy was made but its first lines never ran, a failing HEAD run says nothing about the test."""
    monkeypatch.setattr(redgreen, "_shim_runner", lambda *args: True)  # claims a copy; none exists, none runs
    inv_id = propose(editable_repo, code=WIDGET_TEST, assertion="triple(n) returns three times n.")["id"]
    result = check(editable_repo, inv_id)
    assert result.verdict == "n/a" and "couldn't be started" in result.detail


def test_detecting_an_editable_install(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    env: dict[str, str] = {}
    assert not redgreen.editable_install(root, root, env)  # no virtualenv at all
    site = fake_editable_install(root, str(tmp_path / "elsewhere"))
    assert not redgreen.editable_install(root, root, env)  # a path outside the repository
    fake_editable_install(root, "relative/path")
    assert not redgreen.editable_install(root, root, env)
    fake_editable_install(root, str(site / "vendored"))
    assert not redgreen.editable_install(root, root, env)  # inside the virtualenv itself
    fake_editable_install(root, "import _virtualenv")
    assert not redgreen.editable_install(root, root, env)
    fake_editable_install(root, str(root / "src"))
    assert redgreen.editable_install(root, root, env)  # a `.pth` line, as uv and hatch write

    (site / "_widgets.pth").unlink()
    (site / "__editable___demo_finder.py").write_text(f"MAPPING = {{'demo': '{root.resolve()}/src/demo'}}\n")
    assert redgreen.editable_install(root, root, env)  # an import hook, as setuptools writes
    (site / "__editable___demo_finder.py").unlink()
    info = site / "demo-0.1.dist-info"
    info.mkdir()
    (info / "direct_url.json").write_text(
        json.dumps({"url": f"file://{root.resolve()}", "dir_info": {"editable": True}})
    )
    assert redgreen.editable_install(root, root, env)
    (info / "direct_url.json").write_text(json.dumps({"url": f"file://{root.resolve()}", "dir_info": {}}))
    assert not redgreen.editable_install(root, root, env)  # installed from the folder, but not editable

    other = tmp_path / "active-env/lib/python3.12/site-packages"
    other.mkdir(parents=True)
    (other / "x.pth").write_text(str(root / "src") + "\n")
    assert redgreen.editable_install(root, root, {"VIRTUAL_ENV": str(tmp_path / "active-env")})


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
    assert "Fails without your change: YES" in out.output
    assert "Fails without your change: NO" in out.output
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
    assert "Fails without your change: " not in out.output  # the check itself never ran
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


# --- a supersede request and its replacement are one decision (dogfooding #10, ADR-20261013-7c2e) ---


def swap(root: Path, code: str = PASS) -> tuple[Store, str, str]:
    """A locked rule, a proposed replacement, and the agent's request to swap them."""
    store, cfg = Store(root), load_config(root)
    old = propose(root)["id"]
    lifecycle.approve(store, cfg, old)
    new = propose(root, code=code, title="Retry delay is capped at 60s", assertion="Never above 60 seconds.")["id"]
    lifecycle.request_supersede(store, old, "batch jobs need 60s", new)
    return store, old, new


def test_supersede_with_replacement_is_one_decision(in_repo: Path) -> None:
    store, old, new = swap(in_repo)
    out = runner.invoke(app, ["review"], input="n\na\n")
    assert out.exit_code == 0, out.output
    text = out.output
    assert "To review: 0 proposed rule(s), 1 supersede request(s) (1 with a replacement rule)" in text
    order = [
        f"Supersede request 1 of 1: the rule that would stop running · {old}",
        "Requested: batch jobs need 60s",
        f"Supersede request 1 of 1: its replacement · {new}",
        f"Replaces: {old} · Retry delay is capped (still locked; retired when its supersede request is approved)",
        f"One decision: approving locks {new} and then retires {old}.",
        f"LOCKED {new}",  # the replacement first: at no point is the behavior without a rule
        f"SUPERSEDED {old} (replaced by {new})",
    ]
    assert [text.index(part) for part in order] == sorted(text.index(part) for part in order), text
    assert "== Proposed rules" not in text  # the replacement is not offered a second time, on its own
    assert store.get(new).status == InvStatus.LOCKED
    assert store.get(old).status == InvStatus.SUPERSEDED and store.get(old).superseded_by == new
    assert "approved 1" in text and "superseded 1" in text


@pytest.mark.parametrize("keys", ["n\ns\n", "n\nq\n", "n\n"])  # skip, quit, or the input just ends
def test_stopping_a_swap_changes_nothing_and_never_offers_the_replacement_alone(in_repo: Path, keys: str) -> None:
    store, old, new = swap(in_repo)
    out = runner.invoke(app, ["review"], input=keys)
    assert "Proposed rule 1 of" not in out.output and "LOCKED" not in out.output
    assert store.get(old).status == InvStatus.LOCKED and store.get(new).status == InvStatus.PROPOSED
    assert requests.pending_supersede_ids(store) == {old}


def test_a_failing_replacement_leaves_the_old_rule_locked(in_repo: Path) -> None:
    from .test_lifecycle import FAIL

    store, old, new = swap(in_repo, code=FAIL)
    out = runner.invoke(app, ["review"], input="n\na\n")
    assert f"the replacement was not approved, so {old} stays locked" in out.output
    assert store.get(old).status == InvStatus.LOCKED and store.get(new).status == InvStatus.PROPOSED
    assert requests.pending_supersede_ids(store) == {old} and "superseded" not in out.output.split("Review done")[1]


def test_declining_a_swap_keeps_the_old_rule_and_offers_to_reject_the_replacement(in_repo: Path) -> None:
    store, old, new = swap(in_repo)
    out = runner.invoke(app, ["review"], input="n\nd\ny\n")
    assert out.exit_code == 0, out.output
    assert store.get(old).status == InvStatus.LOCKED and requests.pending_supersede_ids(store) == set()
    rejected = store.get(new)
    assert rejected.status == InvStatus.REJECTED and old in rejected.status_reason
    # Kept as an ordinary proposal instead: it is offered on its own next time.
    store, old, new = swap(in_repo)
    runner.invoke(app, ["review"], input="n\nd\nn\n")
    assert store.get(new).status == InvStatus.PROPOSED
    again = runner.invoke(app, ["review"], input="n\ns\n")
    assert f"Proposed rule 1 of 1 · {new}" in again.output and "Replaces:" not in again.output


def test_a_request_whose_replacement_was_rejected_cannot_be_approved(in_repo: Path) -> None:
    store, old, new = swap(in_repo)
    lifecycle.reject(store, load_config(in_repo), new, "wrong number")
    out = runner.invoke(app, ["review"], input="a\ns\n")
    assert f"Replacement: {new} is REJECTED, so this request can't be approved as it stands." in out.output
    assert "please answer one of: d, s, q" in out.output  # there is no approve key
    assert store.get(old).status == InvStatus.LOCKED


def test_a_retirement_without_replacement_says_nothing_will_protect_the_behavior(in_repo: Path) -> None:
    store, cfg = Store(in_repo), load_config(in_repo)
    old = propose(in_repo)["id"]
    lifecycle.approve(store, cfg, old)
    lifecycle.request_supersede(store, old, "feature removed")
    out = runner.invoke(app, ["review"], input="a\n")
    assert "No replacement: after this, no rule protects this behavior." in out.output
    assert f"SUPERSEDED {old} (no replacement)" in out.output and store.get(old).status == InvStatus.SUPERSEDED


def test_an_unrelated_proposal_is_still_reviewed_after_the_swap(in_repo: Path) -> None:
    """What happened in dogfooding: an unrelated proposal sat between the request and its replacement."""
    other = propose(in_repo, title="Unrelated", assertion="Something else holds.")["id"]
    store, old, new = swap(in_repo)
    out = runner.invoke(app, ["review"], input="n\na\nn\ns\n")
    text = out.output
    assert "To review: 1 proposed rule(s), 1 supersede request(s) (1 with a replacement rule)" in text
    assert text.index(f"SUPERSEDED {old}") < text.index(f"Proposed rule 1 of 1 · {other}")
    assert store.get(new).status == InvStatus.LOCKED and store.get(other).status == InvStatus.PROPOSED


def test_a_locked_replacement_card_says_what_it_replaced(in_repo: Path) -> None:
    store, old, new = swap(in_repo)
    from seamspec import review

    assert review.replaces(store, store.get(new))[0][2].startswith("still locked")
    runner.invoke(app, ["review"], input="n\na\n")
    assert review.replaces(store, store.get(new)) == [(old, "Retry delay is capped", "retired")]
    assert review.replaces(store, store.get(old)) == []


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
    result = check(git_repo, inv_id)
    assert result.verdict == "yes" and not result.new_code  # an assertion failed: not "the code is missing"


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


# --- the readable review (SPEC 15.1, ADR-20261011-8013) -------------------------------------------

READABLE_TEST = (
    "from src.queue import backoff_delay\n\n\n"
    "def test_cap():\n"
    "    delay = backoff_delay(100)\n"
    "    # assert this comment is not a check\n"
    "    assert delay <= 30\n"
    "    assert delay > 0, 'assert in a string is not a check either'\n"
)


def test_review_shows_a_summary_then_the_checks_then_the_full_test(in_repo: Path) -> None:
    inv_id = propose(in_repo, code=READABLE_TEST)["id"]
    propose(in_repo)
    out = runner.invoke(app, ["review"], input="n\ns\nn\ns\n").output
    card = out[out.index(f"Proposed rule 1 of 2 · {inv_id}") :]
    order = ["  Title:  ", "  Rule:   ", "  Where:  ", "  Why:    ", "  Test:   ", "What this test checks",
             "The full test", "Run it now"]  # fmt: skip
    positions = [card.index(part) for part in order]
    assert positions == sorted(positions), "summary first, then the checks, then the test, then the question"
    assert "· 8 lines · 2 checks" in card
    assert "What this test checks (read from the test file by SeamSpec):" in card
    assert "       7  assert delay <= 30" in card and "       8  assert delay > 0, " in card
    assert "       6  " not in card.split("The full test")[0]  # the commented-out assert isn't listed
    # The full test follows in full, with the check lines marked.
    assert "       7 >     assert delay <= 30" in card and "       6 |     # assert this comment is not a check" in card
    assert "       1 | from src.queue import backoff_delay" in card
    assert "Proposed rule 2 of 2" in out


def test_review_warns_about_a_test_with_no_checks_and_a_long_one(in_repo: Path) -> None:
    no_checks = "import subprocess\n\n\ndef test_nothing():\n    subprocess.run(['true'])\n"
    long_test = "def test_long():\n" + "    x = 1\n" * 90 + "    assert x == 1\n"
    propose(in_repo, code=no_checks)
    propose(in_repo, code=long_test)
    out = runner.invoke(app, ["review"], input="n\ns\nn\ns\n").output
    assert "! no recognized assert / expect checks found: look for checks made another way" in out
    assert "! it imports subprocess: a behavior test rarely needs the network or other programs" in out
    assert "! long test (92 lines): a rule test should be short enough to read" in out
    assert out.count("What this test checks") == 1  # the test without checks has no list


def test_long_text_is_cut_visibly_and_dead_end_reasons_are_shown_in_full(in_repo: Path) -> None:
    """Dogfooding finding #7: review cut reasons and origins mid-sentence with nothing to show it."""
    from .conftest import make_dead_end

    reason = "The provider refused. " * 30 + "END-OF-REASON"
    Store(in_repo).create(make_dead_end("de_00000001", failure_symptom=reason[:1000]))
    propose(in_repo, origin_text="word " * 200)
    out = runner.invoke(app, ["review"], input="k\nn\ns\n").output
    assert "Dead end 1 of 1 · de_00000001" in out and "  Tried:    " in out
    assert reason[:1000].strip() in out  # the whole reason: it is what the reviewer judges
    why = next(line for line in out.splitlines() if line.startswith("  Why:    "))
    assert why.endswith("…") and len(why) < 330


def test_vitest_checks_are_labeled_as_a_plain_scan() -> None:
    from seamspec.core import testview

    view = testview.analyze(
        "import { expect, test } from 'vitest';\ntest('x', () => {\n  expect(1).toBe(1);\n});\n", "vitest"
    )
    assert not view.parsed and [(c.line, c.text) for c in view.checks] == [(3, "expect(1).toBe(1);")]
    assert view.facts() == "4 lines · 1 check"


@pytest.mark.parametrize(
    ("code", "checks", "warning"),
    [
        (
            "import pytest\n\ndef test_x():\n    with pytest.raises(ValueError):\n        int('x')\n",
            [(4, "pytest.raises(ValueError)")],
            None,
        ),
        ("def test_x(self):\n    self.assertEqual(1, 1)\n", [(2, "self.assertEqual(1, 1)")], None),
        ("def test_x():\n    assert (\n        1\n        == 1\n    )\n", [(2, "assert ( 1 == 1 )")], None),
        ("def test_x(:\n    assert 1\n", [(2, "assert 1")], "couldn't be parsed as Python"),
        ("import requests\n\ndef test_x():\n    assert requests\n", [(4, "assert requests")], "it imports requests"),
        ("def test_x():\n    pass\n", [], "no recognized assert / expect checks found"),
        (
            "import pytest\n\ndef test_x():\n    if 1 != 1:\n        pytest.fail('no')\n",
            [(5, "pytest.fail('no')")],
            None,
        ),
        (
            "def test_x():\n    if 1 != 1:\n        raise AssertionError('no')\n",
            [(3, "raise AssertionError('no')")],
            None,
        ),
        ("def test_x():\n    raise ValueError('not a check')\n", [], "look for checks made another way"),
        ("from helpers import check\n\ndef test_x():\n    check(1)\n", [], "a helper, an exception"),
    ],
)
def test_what_counts_as_a_check(code: str, checks: list[tuple[int, str]], warning: str | None) -> None:
    from seamspec.core import testview

    view = testview.analyze(code, "pytest")
    assert [(c.line, c.text) for c in view.checks] == checks
    assert (warning is None and not view.warnings) or any(warning in w for w in view.warnings)
