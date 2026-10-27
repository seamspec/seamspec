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
from seamspec.core.models import Invariant
from seamspec.core.store import Store

from .conftest import git
from .test_lifecycle import propose
from .test_trust_gate import commit, gated_repo, human  # noqa: F401 - pytest fixtures

runner = CliRunner()
GOOD = "def backoff_delay(n):\n    return min(0.1 * 2 ** n, 30.0)\n"
BROKEN = "def backoff_delay(n):\n    return 0.1 * 2 ** n  # cap removed\n"


def rule(root: Path, inv_id: str) -> Invariant:
    inv = Store(root).get(inv_id)
    assert isinstance(inv, Invariant)
    return inv


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
    root, inv_id = locked
    (root / "notes.txt").write_text("untracked\n")
    with snapshot.staged(root, load_config(root), [rule(root, inv_id)]) as snap:
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
    root, inv_id = locked
    (root / "notes.txt").write_text("untracked\n")
    monkeypatch.setattr(snapshot, "editable_install", lambda *args: True)
    monkeypatch.setattr(snapshot, "shim_runner", lambda *args: None)
    cfg = load_config(root)
    with pytest.raises(snapshot.SnapshotError, match="editable mode"), snapshot.staged(root, cfg, [rule(root, inv_id)]):
        pass
    with snapshot.staged(root, cfg, []):  # no rule uses it: nothing to refuse
        pass


def test_node_runners_need_no_redirect(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    scripts = {
        "npx": "#!/usr/bin/env node",
        "jest": "#!/usr/bin/env -S node --no-warnings",
        "bunx": "#!/opt/bun/bin/bun",
        "pytest": f"#!{sys.executable}",
        "uv": "\x7fELF",  # a binary may well start Python
        "wrapped": "#!/opt/node-tools/sh",  # "node" in a folder name isn't Node (#101)
        "envpy": "#!/usr/bin/env PYTHONPATH=src python3",
        "unset": "#!/usr/bin/env -S -u node python3",  # `-u node` unsets a variable; Python starts
        "clean": "#!/usr/bin/env -i node",  # an option we don't parse: no exemption
        "quoted": "#!/usr/bin/env -S PROBE='x node y' python3",  # quoting we don't parse: no exemption
    }
    for name, first in scripts.items():
        (bin_dir / name).write_text(first + "\n")
        (bin_dir / name).chmod(0o755)
    cfg = Config(runners={n: RunnerCfg(cmd=[n], filename="test_{id}.py", env={"PATH": str(bin_dir)}) for n in scripts})
    repo = tmp_path / "repo"
    assert [n for n in scripts if redgreen.starts_without_python(cfg, n, tmp_path, repo)] == ["npx", "jest", "bunx"]


def test_a_node_script_in_the_repository_itself_gets_no_exemption(tmp_path: Path) -> None:
    """Started by its path inside the repo, it runs the working tree's copy (#101). One in
    `node_modules` is a dependency, linked into the copy, and still counts as Node."""
    repo = tmp_path / "repo"
    for rel in ("tools/check.cjs", "node_modules/.bin/vitest"):
        (repo / rel).parent.mkdir(parents=True)
        (repo / rel).write_text("#!/usr/bin/env node\n")
    cfg = Config(
        runners={
            "local": RunnerCfg(cmd=[str(repo / "tools/check.cjs")], filename="t_{id}.ts"),
            "dep": RunnerCfg(cmd=[str(repo / "node_modules/.bin/vitest")], filename="t_{id}.ts"),
        }
    )
    assert not redgreen.starts_without_python(cfg, "local", tmp_path / "snap", repo)
    assert redgreen.starts_without_python(cfg, "dep", tmp_path / "snap", repo)


def test_a_dependency_of_a_project_in_a_subfolder_still_counts_as_node(tmp_path: Path) -> None:
    """A monorepo: SeamSpec's project is `repo/app`, its vitest in `repo/app/node_modules` (#101)."""
    repo = tmp_path / "repo"
    vitest = repo / "app/node_modules/.bin/vitest"
    vitest.parent.mkdir(parents=True)
    vitest.write_text("#!/usr/bin/env node\n")
    cfg = Config(runners={"vitest": RunnerCfg(cmd=[str(vitest)], filename="t_{id}.ts")})
    assert redgreen.starts_without_python(cfg, "vitest", tmp_path / "snap", repo, repo / "app")
    assert not redgreen.starts_without_python(cfg, "vitest", tmp_path / "snap", repo)  # app/ itself isn't a dependency


def test_a_relative_path_entry_is_read_from_the_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`PATH=tools` finds the copy's `tools/check`, the one the runner starts, not the working tree's (#101)."""
    snap, here = tmp_path / "snap", tmp_path / "here"
    for folder, first in ((snap, f"#!{sys.executable}"), (here, "#!/usr/bin/env node")):
        (folder / "tools").mkdir(parents=True)
        (folder / "tools/check").write_text(first + "\n")
        (folder / "tools/check").chmod(0o755)
    monkeypatch.chdir(here)
    cfg = Config(runners={"check": RunnerCfg(cmd=["check"], filename="t_{id}.py", env={"PATH": "tools"})})
    assert not redgreen.starts_without_python(cfg, "check", snap, tmp_path / "repo")


def outside(root: Path, inv_id: str, harness: str) -> Invariant:
    """The rule with its test kept outside `.seamspec/`, as vitest keeps it."""
    inv = rule(root, inv_id)
    return inv.model_copy(update={"verification": inv.verification.model_copy(update={"harness_path": harness})})


def test_rule_tests_outside_the_ledger_come_from_disk(locked: tuple[Path, str]) -> None:
    """vitest keeps rule tests in `tests/seamspec/`. One approved but not staged yet still applies;
    a tracked one changed after `git add` is refused, as for `.seamspec/`."""
    root, inv_id = locked
    cfg = load_config(root)
    inv = outside(root, inv_id, "tests/seamspec/inv_new.test.ts")
    (root / "tests/seamspec").mkdir(parents=True)
    (root / "tests/seamspec/inv_new.test.ts").write_text("// approved, not staged\n")
    with snapshot.staged(root, cfg, [inv]) as snap:
        assert (snap.root / "tests/seamspec/inv_new.test.ts").read_text() == "// approved, not staged\n"
    git(root, "add", "tests/seamspec")
    (root / "tests/seamspec/inv_new.test.ts").write_text("// changed after git add\n")
    with pytest.raises(snapshot.SnapshotError, match="git add tests/seamspec"), snapshot.staged(root, cfg, [inv]):
        pass


def test_only_the_rules_own_tests_come_from_disk(locked: tuple[Path, str]) -> None:
    """Even with the rule test at the top of the project, an unstaged module next to it stays out:
    the commit doesn't contain it, so the check mustn't either (#101)."""
    root, inv_id = locked
    (root / "inv_new.test.ts").write_text("// the rule's test\n")
    (root / "src/limits.py").write_text("LIMIT = 30\n")  # untracked: not in the commit
    with snapshot.staged(root, load_config(root), [outside(root, inv_id, "inv_new.test.ts")]) as snap:
        assert (snap.root / "inv_new.test.ts").exists() and not (snap.root / "src/limits.py").exists()


def test_a_link_in_the_staged_files_is_replaced_never_written_through(tmp_path: Path) -> None:
    """A staged link `tests/seamspec/inv_x.test.ts -> ../../src/queue.py` must not let the rule
    test from disk overwrite the staged `src/queue.py`; a linked folder on the way is refused (#101)."""
    snap, disk = tmp_path / "snap", tmp_path / "disk"
    (snap / "src").mkdir(parents=True)
    (snap / "src/queue.py").write_text(GOOD)
    (snap / "tests/seamspec").mkdir(parents=True)
    (snap / "tests/seamspec/inv_x.test.ts").symlink_to("../../src/queue.py")
    (disk / "tests/seamspec").mkdir(parents=True)
    (disk / "tests/seamspec/inv_x.test.ts").write_text("// the rule's test\n")
    snapshot._place(disk / "tests/seamspec/inv_x.test.ts", snap, "tests/seamspec/inv_x.test.ts")
    assert (snap / "src/queue.py").read_text() == GOOD
    assert not (snap / "tests/seamspec/inv_x.test.ts").is_symlink()
    (snap / "lib").symlink_to("src", target_is_directory=True)
    (disk / "lib").mkdir()
    (disk / "lib/inv_y.test.ts").write_text("// another\n")
    with pytest.raises(snapshot.SnapshotError, match="is a link in the staged files"):
        snapshot._place(disk / "lib/inv_y.test.ts", snap, "lib/inv_y.test.ts")
    assert not (snap / "src/inv_y.test.ts").exists()


def test_a_rule_test_path_outside_the_project_is_refused_before_anything_is_touched(tmp_path: Path) -> None:
    """An absolute path would make `snap_root / rel` the real file, which `_place` would replace (#101)."""
    snap, real = tmp_path / "snap", tmp_path / "repo/src/queue.py"
    snap.mkdir()
    real.parent.mkdir(parents=True)
    real.write_text(GOOD)
    for rel in (
        str(real),
        "../repo/src/queue.py",
        "\\repo\\src\\queue.py",
        "\\\\host\\share\\x",
        "C:repo/src/queue.py",
        "src\\..\\..\\x",
    ):
        with pytest.raises(snapshot.SnapshotError, match="isn't a path inside the project"):
            snapshot._place(tmp_path / "anything", snap, rel)
    assert real.read_text() == GOOD
