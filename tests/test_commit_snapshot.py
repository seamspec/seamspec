"""The commit check tests what the commit records, not the files on disk (SPEC §16.4, ADR-20261014-3b1e).

Found testing on Antigravity: broken code was staged, then fixed on disk only. The gate ran the
working tree, passed, and the commit recorded the broken file.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from seamspec.cli import app
from seamspec.core import lifecycle, redgreen, snapshot
from seamspec.core.config import Config, RunnerCfg, load_config
from seamspec.core.store import Store

from .conftest import git
from .test_lifecycle import propose
from .test_trust_gate import commit, gated_repo, human  # noqa: F401 - pytest fixtures

runner = CliRunner()
GOOD = "def backoff_delay(n):\n    return min(0.1 * 2 ** n, 30.0)\n"
BROKEN = "def backoff_delay(n):\n    return 0.1 * 2 ** n  # cap removed\n"


def commit_staged(root: Path, message: str) -> subprocess.CompletedProcess[str]:
    """`git commit` of whatever is staged, with hooks, without staging anything first."""
    env = {**os.environ, "GIT_AUTHOR_NAME": "Maya Rao", "GIT_AUTHOR_EMAIL": "maya@example.com",
           "GIT_COMMITTER_NAME": "Maya Rao", "GIT_COMMITTER_EMAIL": "maya@example.com"}  # fmt: skip
    env.pop("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", None)
    return subprocess.run(["git", "commit", "-q", "-m", message], cwd=root, capture_output=True, text=True, env=env)


@pytest.fixture
def locked(gated_repo: Path, human: None) -> tuple[Path, str]:  # noqa: F811
    root = gated_repo
    inv_id = propose(root)["id"]
    lifecycle.approve(Store(root), load_config(root), inv_id)
    assert commit(root, "lock retry cap").returncode == 0
    return root, inv_id


def test_broken_code_staged_then_fixed_on_disk_is_blocked(locked: tuple[Path, str]) -> None:
    root, inv_id = locked
    (root / "src/queue.py").write_text(BROKEN)
    git(root, "add", "src/queue.py")
    (root / "src/queue.py").write_text(GOOD + "# cap kept\n")  # fixed on disk, not staged again

    blocked = commit_staged(root, "remove the cap")
    assert blocked.returncode != 0, "the gate passed a commit whose staged code breaks a locked rule"
    assert "SeamSpec: commit blocked." in blocked.stderr and inv_id in blocked.stderr
    assert "Checked what this commit records (your staged files)" in blocked.stderr
    assert git(root, "show", ":src/queue.py") == BROKEN  # the gate never touches the index or the files

    git(root, "add", "src/queue.py")  # staging the fix lets the commit through
    assert commit_staged(root, "keep the cap").returncode == 0


def test_good_code_staged_and_broken_on_disk_commits(locked: tuple[Path, str]) -> None:
    """The commit records the good version, so it passes; the broken file on disk stays unstaged."""
    root, _ = locked
    (root / "src/queue.py").write_text(GOOD + "\n# tidy\n")
    git(root, "add", "src/queue.py")
    (root / "src/queue.py").write_text(BROKEN)

    result = commit_staged(root, "tidy")
    assert result.returncode == 0, result.stderr
    assert (root / "src/queue.py").read_text() == BROKEN  # left alone


def test_code_that_needs_an_unstaged_file_is_blocked(locked: tuple[Path, str]) -> None:
    root, _ = locked
    (root / "src/limits.py").write_text("CAP = 30.0\n")  # on disk only, never staged
    (root / "src/queue.py").write_text(
        "from src.limits import CAP\n\n\ndef backoff_delay(n):\n    return min(0.1 * 2 ** n, CAP)\n"
    )
    git(root, "add", "src/queue.py")

    blocked = commit_staged(root, "move the cap")
    assert blocked.returncode != 0 and "Checked what this commit records" in blocked.stderr

    git(root, "add", "src/limits.py")
    assert commit_staged(root, "move the cap").returncode == 0


def test_a_staged_ledger_that_differs_from_disk_is_refused(locked: tuple[Path, str]) -> None:
    root, inv_id = locked
    test_file = root / f".seamspec/tests/test_{inv_id}.py"
    approved = test_file.read_text()
    test_file.write_text("def test_cap():\n    assert True\n")
    git(root, "add", str(test_file))  # a weakened test staged...
    test_file.write_text(approved)  # ...and the approved one put back on disk
    (root / "src/queue.py").write_text(BROKEN)
    git(root, "add", "src/queue.py")

    blocked = commit_staged(root, "sneak it in")
    assert blocked.returncode != 0
    assert "SeamSpec's files staged for this commit differ from the ones on disk" in blocked.stderr


def test_a_rule_approved_but_not_staged_still_applies(gated_repo: Path, human: None) -> None:  # noqa: F811
    root = gated_repo
    assert commit(root, "init").returncode == 0
    inv_id = propose(root)["id"]
    lifecycle.approve(Store(root), load_config(root), inv_id)  # the rule's files stay untracked
    (root / "src/queue.py").write_text(BROKEN)
    git(root, "add", "src/queue.py")

    blocked = commit_staged(root, "remove the cap")
    assert blocked.returncode != 0 and inv_id in blocked.stderr


def test_a_clean_tree_runs_as_before(locked: tuple[Path, str], monkeypatch: pytest.MonkeyPatch) -> None:
    root, _ = locked
    monkeypatch.chdir(root)
    assert not snapshot.differs(root)
    result = runner.invoke(app, ["verify", "--all", "--gate"])
    assert result.exit_code == 0 and "(on the staged files)" not in result.output


def test_editable_install_without_a_redirect_fails_closed(
    locked: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = locked
    (root / "notes.txt").write_text("untracked\n")  # disk differs from the index
    monkeypatch.chdir(root)
    monkeypatch.setattr(snapshot, "editable_install", lambda *args: True)
    monkeypatch.setattr(snapshot, "shim_runner", lambda *args: False)
    result = runner.invoke(app, ["verify", "--all", "--gate"])
    assert result.exit_code == 1 and "installed in editable mode" in result.output


def test_the_copy_is_removed(locked: tuple[Path, str]) -> None:
    root, _ = locked
    (root / "notes.txt").write_text("untracked\n")
    with snapshot.staged(root, load_config(root), ["pytest"]) as snap:
        copy = snap.root
        assert (copy / "src/queue.py").read_text() == GOOD
        assert not (copy / "notes.txt").exists() and not (copy / ".seamspec/.local").exists()
    assert not copy.exists()


# --- found by the catch-up review of #53-#95 (ADR-20261026-5b8e) ---------------------------------------


def test_a_commit_with_no_rules_to_run_is_not_blocked_by_an_editable_install(
    gated_repo: Path,  # noqa: F811
    human: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Right after `seamspec init`: no approved rules, an editable install (uv's default) and a file
    not staged yet. Nothing runs, so there is nothing that could import the working tree's code."""
    (gated_repo / "notes.txt").write_text("untracked\n")
    monkeypatch.chdir(gated_repo)
    monkeypatch.setattr(snapshot, "editable_install", lambda *args: True)
    monkeypatch.setattr(snapshot, "shim_runner", lambda *args: None)
    result = runner.invoke(app, ["verify", "--all", "--gate"])
    assert result.exit_code == 0, result.output


def test_each_runner_that_ran_needs_its_own_redirect(tmp_path: Path) -> None:
    """One redirected runner says nothing about another: `.venv/bin/pytest` (started by its path, so
    never redirected) could import the working tree's code while `pytest` was redirected."""
    shims = tmp_path / "bin"
    shims.mkdir()
    (shims / "applied.pytest").write_text("")
    snap = snapshot.Snapshot(tmp_path, shims, True, True, evidence={"pytest": "applied.pytest", "unit": "applied.x"})
    assert snap.trustworthy(["pytest"]) and snap.trustworthy([])
    assert not snap.trustworthy(["pytest", "by-path"])  # no redirect at all
    assert not snap.trustworthy(["unit"])  # a copy was made, but its redirect never ran
    assert snapshot.Snapshot(tmp_path, shims, True, True, no_python={"vitest"}).trustworthy(["vitest"])
    assert snapshot.Snapshot(tmp_path, shims, False, False).trustworthy(["by-path"])  # not editable


def test_a_runner_that_cant_be_redirected_is_refused_before_anything_runs(
    locked: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = locked
    (root / "notes.txt").write_text("untracked\n")
    monkeypatch.setattr(snapshot, "editable_install", lambda *args: True)
    monkeypatch.setattr(snapshot, "shim_runner", lambda *args: None)
    cfg = load_config(root)
    with pytest.raises(snapshot.SnapshotError, match="editable mode"), snapshot.staged(root, cfg, ["pytest"]):
        pass
    with snapshot.staged(root, cfg, []):  # no rule uses it: nothing to refuse
        pass


def test_node_runners_need_no_redirect(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, first in (("npx", "#!/usr/bin/env node"), ("pytest", f"#!{sys.executable}"), ("uv", "\x7fELF")):
        (bin_dir / name).write_text(first + "\n")
        (bin_dir / name).chmod(0o755)
    cfg = Config(
        runners={
            n: RunnerCfg(cmd=[n], filename="test_{id}.py", env={"PATH": str(bin_dir)}) for n in ("npx", "pytest", "uv")
        }
    )
    assert redgreen.starts_without_python(cfg, "npx", tmp_path)
    assert not redgreen.starts_without_python(cfg, "pytest", tmp_path)
    assert not redgreen.starts_without_python(cfg, "uv", tmp_path)  # a binary may well start Python


def test_rule_tests_outside_the_ledger_come_from_disk(locked: tuple[Path, str]) -> None:
    """vitest keeps rule tests in `tests/seamspec/`. One approved but not staged yet still applies;
    a tracked one changed after `git add` is refused, as for `.seamspec/`."""
    root, _ = locked
    cfg = load_config(root)
    cfg.runners["pytest"] = cfg.runners["pytest"].model_copy(update={"harness_dir": "tests/seamspec"})
    (root / "tests/seamspec").mkdir(parents=True)
    (root / "tests/seamspec/inv_new.test.ts").write_text("// approved, not staged\n")
    with snapshot.staged(root, cfg, []) as snap:
        assert (snap.root / "tests/seamspec/inv_new.test.ts").read_text() == "// approved, not staged\n"
    git(root, "add", "tests/seamspec")
    (root / "tests/seamspec/inv_new.test.ts").write_text("// changed after git add\n")
    with pytest.raises(snapshot.SnapshotError, match="git add tests/seamspec"), snapshot.staged(root, cfg, []):
        pass
