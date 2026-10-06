"""Consent, trust, `seamspec verify` and the pre-commit gate (SPEC §12.4.5, §12.4.6, §16.4).

The end-to-end tests here are Week 2's exit criteria for Python: real git, the real installed hook,
real pytest. (TypeScript: tests/test_verifier_vitest.py.)
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from seamspec.cli import app
from seamspec.core import lifecycle, trust
from seamspec.core.config import load_config
from seamspec.core.models import InvStatus
from seamspec.core.store import Store
from seamspec.core.tree import changed_files
from seamspec.installers import git_hooks, scaffold

from .conftest import git
from .test_lifecycle import PASS, propose

runner = CliRunner()


@pytest.fixture
def human(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")


def commit(root: Path, message: str) -> subprocess.CompletedProcess[str]:
    """`git commit` with hooks enabled, as a developer would run it."""
    git(root, "add", "-A")
    env = {**os.environ, "GIT_AUTHOR_NAME": "Maya Rao", "GIT_AUTHOR_EMAIL": "maya@example.com",
           "GIT_COMMITTER_NAME": "Maya Rao", "GIT_COMMITTER_EMAIL": "maya@example.com"}  # fmt: skip
    env.pop("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", None)
    return subprocess.run(["git", "commit", "-q", "-m", message], cwd=root, capture_output=True, text=True, env=env)


@pytest.fixture
def gated_repo(tmp_path: Path) -> Path:
    """A git repo set up by the real CLI with --accept-auto-run: hook installed, clone trusted."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    (tmp_path / "src").mkdir()
    (tmp_path / "src/__init__.py").write_text("")
    (tmp_path / "src/queue.py").write_text("def backoff_delay(n):\n    return min(0.1 * 2 ** n, 30.0)\n")
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.name", "Maya Rao")
    git(tmp_path, "config", "user.email", "maya@example.com")
    result = runner.invoke(app, ["init", "--path", str(tmp_path), "--accept-auto-run"])
    assert result.exit_code == 0, result.output
    assert "git pre-commit hook" in result.output
    return tmp_path


# --- the Week 2 exit criteria (Python) ---------------------------------------------------------------


def test_pre_commit_blocks_a_regression_naming_the_rule(gated_repo: Path, human: None) -> None:
    root = gated_repo
    assert commit(root, "init").returncode == 0  # nothing locked yet: the gate passes

    inv_id = propose(root)["id"]
    lifecycle.approve(Store(root), load_config(root), inv_id)
    assert commit(root, "lock retry cap").returncode == 0

    (root / "src/queue.py").write_text("def backoff_delay(n):\n    return 0.1 * 2 ** n  # cap removed\n")
    blocked = commit(root, "remove the cap")
    assert blocked.returncode != 0, "pre-commit let a regression through"
    assert f"[FAIL] {inv_id} (pytest)" in blocked.stderr
    assert "supersede" in blocked.stderr
    assert git(root, "log", "--oneline").count("\n") == 2  # the commit didn't happen

    (root / "src/queue.py").write_text("def backoff_delay(n):\n    return min(0.1 * 2 ** n, 30.0)\n")
    assert commit(root, "keep the cap").returncode == 0


def test_pre_commit_blocks_a_silent_retirement(gated_repo: Path, human: None) -> None:
    root = gated_repo
    inv_id = propose(root)["id"]
    lifecycle.approve(Store(root), load_config(root), inv_id)
    assert commit(root, "lock").returncode == 0
    store = Store(root)
    store.save(store.get(inv_id).model_copy(update={"status": InvStatus.SUPERSEDED, "status_reason": "x"}))
    blocked = commit(root, "sneaky")
    assert blocked.returncode != 0 and "outside the SeamSpec CLI" in blocked.stderr


def test_untrusted_clone_runs_nothing(gated_repo: Path, human: None, tmp_path_factory) -> None:
    root = gated_repo
    marker = root.parent / "harness-ran.txt"
    code = f"open({str(marker)!r}, 'a').write('x')\n" + PASS
    inv_id = propose(root, code=code)["id"]
    lifecycle.approve(Store(root), load_config(root), inv_id)
    assert commit(root, "lock").returncode == 0
    marker.unlink()

    clone = tmp_path_factory.mktemp("clone") / "repo"
    git(root.parent, "clone", "-q", str(root), str(clone))
    assert not (clone / ".seamspec/.local/trust.json").exists()
    result = subprocess.run(
        ["seamspec", "verify", "--all", "--gate"], cwd=clone, capture_output=True, text=True,
        env={k: v for k, v in os.environ.items() if k != "SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE"},
    )  # fmt: skip
    assert result.returncode == 1 and "not trusted" in result.stderr
    assert not marker.exists(), "an untrusted clone ran a test"


# --- trust ------------------------------------------------------------------------------------------


def test_init_trusts_the_config_it_writes(py_repo: Path) -> None:
    store, cfg = Store(py_repo), load_config(py_repo)
    assert trust.state(store, cfg).trusted
    assert trust.execution_permitted(store, cfg) == (True, "")


def test_changed_runner_command_needs_re_trust(py_repo: Path) -> None:
    cfg_path = py_repo / ".seamspec/config.toml"
    cfg_path.write_text(cfg_path.read_text().replace('"-q",', '"-q", "-x",'))
    store, cfg = Store(py_repo), load_config(py_repo)
    st = trust.state(store, cfg)
    assert not st.trusted and "runner commands" in st.reason
    trust.grant(store, cfg, "Maya")
    assert trust.state(store, cfg).trusted


def test_env_passthrough_change_needs_re_trust(py_repo: Path) -> None:
    cfg_path = py_repo / ".seamspec/config.toml"
    cfg_path.write_text(cfg_path.read_text().replace("env_passthrough = []", 'env_passthrough = ["AWS_SECRET"]'))
    assert not trust.state(Store(py_repo), load_config(py_repo)).trusted


def test_harness_level_needs_re_trust_for_new_tests(py_repo: Path, human: None) -> None:
    cfg_path = py_repo / ".seamspec/config.toml"
    cfg_path.write_text(cfg_path.read_text().replace('trust_level = "runners"', 'trust_level = "harness"'))
    store, cfg = Store(py_repo), load_config(py_repo)
    trust.grant(store, cfg, "Maya")
    inv_id = propose(py_repo)["id"]
    lifecycle.approve(store, cfg, inv_id)
    st = trust.state(store, cfg)
    assert not st.trusted and st.new_or_changed_tests == [inv_id] and "locked test" in st.reason


def test_runners_level_ignores_new_tests(py_repo: Path, human: None) -> None:
    inv_id = propose(py_repo)["id"]
    lifecycle.approve(Store(py_repo), load_config(py_repo), inv_id)
    st = trust.state(Store(py_repo), load_config(py_repo))
    assert st.trusted and st.new_or_changed_tests == [inv_id]


def test_no_consent_means_no_automatic_runs(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("")
    scaffold.init(tmp_path, mode="advisory")
    allowed, why = trust.execution_permitted(Store(tmp_path), load_config(tmp_path))
    assert not allowed and "advisory" in why


def test_trust_cli(py_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(py_repo)
    (py_repo / ".seamspec/.local/trust.json").unlink()
    shown = runner.invoke(app, ["trust", "--show"])
    assert "NOT trusted (this clone has never been trusted)" in shown.output
    refused = runner.invoke(app, ["trust"], input="y\n")
    assert refused.exit_code == 1 and "interactive terminal" in refused.output
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")
    ok = runner.invoke(app, ["trust"], input="y\n")
    assert ok.exit_code == 0 and "[pytest] pytest -c .seamspec/pytest.ini" in ok.output and "Trusted." in ok.output


@pytest.mark.parametrize("answer", ["y", "n"])
def test_init_on_a_fresh_clone_asks_once(py_repo: Path, monkeypatch: pytest.MonkeyPatch, answer: str) -> None:
    """A teammate's clone: one question covers auto-run consent and trust in the committed runners."""
    for name in ("trust.json", "consent.json"):
        (py_repo / ".seamspec/.local" / name).unlink()
    monkeypatch.setattr("seamspec.cli._interactive", lambda: True)
    result = runner.invoke(app, ["init", "--path", str(py_repo), "--no-claude-md"], input=f"{answer}\n")
    assert result.exit_code == 0, result.output
    assert "[pytest] pytest -c .seamspec/pytest.ini" in result.output
    assert result.output.count("[y/N]") == 1 and "with these commands" in result.output
    store, cfg = Store(py_repo), load_config(py_repo)
    assert trust.state(store, cfg).trusted is (answer == "y")
    assert trust.execution_permitted(store, cfg)[0] is (answer == "y")
    assert ("run `seamspec trust`" in result.output) is (answer == "n")


def test_scripted_init_never_trusts_a_clone(py_repo: Path) -> None:
    """--accept-auto-run is consent only: trusting committed commands needs a human at a terminal."""
    (py_repo / ".seamspec/.local/trust.json").unlink()
    result = runner.invoke(app, ["init", "--path", str(py_repo), "--no-claude-md", "--accept-auto-run"])
    assert result.exit_code == 0 and "run `seamspec trust`" in result.output
    assert not trust.state(Store(py_repo), load_config(py_repo)).trusted


# --- pre-commit installer ----------------------------------------------------------------------------


def test_hook_is_installed_and_idempotent(gated_repo: Path) -> None:
    hook = gated_repo / ".git/hooks/pre-commit"
    assert os.access(hook, os.X_OK) and "seamspec verify --all --gate" in hook.read_text()
    assert 'PATH="$PATH:$HOME/.local/bin"' in hook.read_text()  # GUI git clients (SPEC §16.4)
    assert git_hooks.install_pre_commit(gated_repo).status == "unchanged"


def test_foreign_hook_and_hook_managers_are_left_alone(git_repo: Path) -> None:
    hook = git_repo / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\necho mine\n")
    result = git_hooks.install_pre_commit(git_repo)
    assert result.status == "manual" and hook.read_text() == "#!/bin/sh\necho mine\n"
    hook.unlink()
    (git_repo / ".pre-commit-config.yaml").write_text("repos: []\n")
    result = git_hooks.install_pre_commit(git_repo)
    assert result.status == "manual" and "pre-commit manages your git hooks" in result.message
    assert not hook.exists()


def test_hook_for_seamspec_in_a_subfolder(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q", "-b", "main")
    sub = tmp_path / "services/api"
    sub.mkdir(parents=True)
    result = git_hooks.install_pre_commit(sub)
    assert result.status == "created"
    assert (
        'cd "$(git rev-parse --show-toplevel)/services/api" || exit 1'
        in (tmp_path / ".git/hooks/pre-commit").read_text()
    )


def test_no_git_no_hook(tmp_path: Path) -> None:
    assert git_hooks.install_pre_commit(tmp_path).status == "skipped"


# --- seamspec verify ---------------------------------------------------------------------------------


@pytest.fixture
def in_repo(git_repo: Path, monkeypatch: pytest.MonkeyPatch, human: None) -> Path:
    monkeypatch.chdir(git_repo)
    return git_repo


def test_verify_all_pass_and_fail(in_repo: Path) -> None:
    inv_id = propose(in_repo)["id"]
    lifecycle.approve(Store(in_repo), load_config(in_repo), inv_id)
    ok = runner.invoke(app, ["verify"])
    assert ok.exit_code == 0 and "1 invariant(s) passed" in ok.output
    (in_repo / "src/queue.py").write_text("def backoff_delay(n):\n    return 99\n")
    bad = runner.invoke(app, ["verify", "--json"])
    data = json.loads(bad.output)
    assert bad.exit_code == 1 and data["failing_ids"] == [inv_id] and data["passed"] is False
    assert json.loads((in_repo / ".seamspec/.local/last_verify.json").read_text())["passed"] is False


def test_verify_changed_selects_by_scope(in_repo: Path) -> None:
    inv_id = propose(in_repo)["id"]
    lifecycle.approve(Store(in_repo), load_config(in_repo), inv_id)
    git(in_repo, "add", "-A")
    git(in_repo, "commit", "-q", "-m", "lock")
    assert "0 invariant(s) passed" in runner.invoke(app, ["verify", "--changed"]).output
    (in_repo / "src/queue.py").write_text((in_repo / "src/queue.py").read_text() + "\n")
    assert "1 invariant(s) passed" in runner.invoke(app, ["verify", "--changed"]).output


def test_verify_proposed_runs_in_place_then_cleans_up(in_repo: Path) -> None:
    good = propose(in_repo)["id"]
    bad = propose(in_repo, code="def test_x():\n    assert False\n")["id"]
    assert runner.invoke(app, ["verify", "--proposed", good]).exit_code == 0
    out = runner.invoke(app, ["verify", "--proposed", bad])
    assert out.exit_code == 1 and f"[FAIL] {bad}" in out.output
    assert not list((in_repo / ".seamspec/tests").glob("test_inv_*.py"))
    assert Store(in_repo).get(good).status == InvStatus.PROPOSED
    locked_err = runner.invoke(app, ["verify", "--proposed", "inv_00000000"])
    assert locked_err.exit_code == 1


def test_verify_untrusted_fails_without_a_terminal(in_repo: Path) -> None:
    (in_repo / ".seamspec/.local/trust.json").unlink()
    result = runner.invoke(app, ["verify"])
    assert result.exit_code == 1 and "not trusted" in result.output
    assert runner.invoke(app, ["verify", "--ci"]).exit_code == 0  # CI policy is the consent


def test_gate_reports_pending_reviews(in_repo: Path) -> None:
    propose(in_repo)
    result = runner.invoke(app, ["verify", "--gate"])
    assert result.exit_code == 0 and "1 item(s) awaiting review" in result.output


def test_changed_files(git_repo: Path) -> None:
    assert changed_files(git_repo) == []
    (git_repo / "src/queue.py").write_text("x = 1\n")
    (git_repo / "src/new.py").write_text("")
    (git_repo / "ignored.log").write_text("")
    (git_repo / ".gitignore").write_text((git_repo / ".gitignore").read_text() + "*.log\n")
    assert changed_files(git_repo) == [".gitignore", "src/new.py", "src/queue.py"]
    assert changed_files(git_repo.parent / "not-a-repo-dir-xyz") is None
