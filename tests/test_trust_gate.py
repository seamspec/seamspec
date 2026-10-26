"""Consent, trust, `seamspec verify` and the pre-commit gate (SPEC §12.4.5, §12.4.6, §16.4).

The end-to-end tests here are Week 2's exit criteria for Python: real git, the real installed hook,
real pytest. (TypeScript: tests/test_verifier_vitest.py.)
"""

from __future__ import annotations

import json
import os
import shutil
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
    # Dogfooding #11: the refusal names the rule by title and shows the check that failed, not 80 lines
    # of runner output.
    assert "SeamSpec: commit blocked." in blocked.stderr and "1 rule fails:" in blocked.stderr
    assert f"  {inv_id} · Retry delay is capped\n    line 5: assert backoff_delay(100) <= 30\n" in blocked.stderr
    assert "Full test output: `seamspec verify --all`" in blocked.stderr
    assert "short test summary info" not in blocked.stderr and f"[FAIL] {inv_id}" not in blocked.stderr
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
    assert result.returncode == 1 and "isn't set up for this clone" in result.stderr  # a fresh clone: run init
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
    result = runner.invoke(
        app, ["init", "--path", str(py_repo), "--no-claude-md", "--no-plugin", "--no-ci"], input=f"{answer}\n"
    )
    assert result.exit_code == 0, result.output
    assert "[pytest] pytest -c .seamspec/pytest.ini" in result.output
    assert result.output.count("[y/N]") == 1 and "with these commands" in result.output
    store, cfg = Store(py_repo), load_config(py_repo)
    assert trust.state(store, cfg).trusted is (answer == "y")
    assert trust.execution_permitted(store, cfg)[0] is (answer == "y")
    assert ("run `seamspec trust`" in result.output) is (answer == "n")


def test_rerunning_init_keeps_an_earlier_yes(py_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Rerunning init (e.g. to add an editor) asked again with "No" as the default: one Enter would have
    switched the checks off (hands-on test, ADR-20261017-7b0e)."""
    store = Store(py_repo)
    assert trust.consent_given(store) and trust.state(store, load_config(py_repo)).trusted
    monkeypatch.setattr("seamspec.cli._interactive", lambda: True)
    result = runner.invoke(
        app, ["init", "--path", str(py_repo), "--no-claude-md", "--no-plugin", "--no-ci"], input="\n"
    )
    assert result.exit_code == 0, result.output
    assert "Allow automatic test runs" not in result.output and "already allowed on this machine" in result.output
    assert trust.consent_given(store) and trust.execution_permitted(store, load_config(py_repo))[0]


def test_clone_trust_is_bound_to_what_was_shown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--mode strict on an advisory clone switches trust_level to "harness" after the screen showed
    "runners": the yes no longer matches what's on disk, so nothing is trusted."""
    (tmp_path / "pyproject.toml").write_text("")
    scaffold.init(tmp_path, mode="advisory", actor="Maya")
    (tmp_path / ".seamspec/.local/trust.json").unlink()
    monkeypatch.setattr("seamspec.cli._interactive", lambda: True)
    result = runner.invoke(
        app,
        ["init", "--path", str(tmp_path), "--mode", "strict", "--no-claude-md", "--no-plugin", "--no-ci"],
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    assert "trust level: runners" in result.output and "changed after they were shown" in result.output
    cfg = load_config(tmp_path)
    assert cfg.execution.trust_level == "harness" and not trust.state(Store(tmp_path), cfg).trusted


def test_scaffold_grants_only_the_shown_trust_hash(py_repo: Path) -> None:
    store = Store(py_repo)
    (py_repo / ".seamspec/.local/trust.json").unlink()
    shown = trust.trust_hash(load_config(py_repo), trust.locked_harnesses(store))
    cfg_path = py_repo / ".seamspec/config.toml"
    cfg_path.write_text(cfg_path.read_text().replace("env_passthrough = []", 'env_passthrough = ["AWS_SECRET"]'))
    scaffold.init(py_repo, auto_run=True, claude_md=False, trust_shown=shown)  # edited while the prompt was open
    assert not trust.state(store, load_config(py_repo)).trusted
    scaffold.init(py_repo, auto_run=True, claude_md=False, trust_shown=trust.trust_hash(load_config(py_repo), {}))
    assert trust.state(store, load_config(py_repo)).trusted


def test_trust_screens_escape_committed_config(py_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Someone else's config must not be able to repaint the screen it is being trusted on."""
    cfg_path = py_repo / ".seamspec/config.toml"
    text = cfg_path.read_text().replace(
        'report = "junit"', 'report = "junit"\nenv = { X = "a\\u001b[2J\\nAll good. y" }', 1
    )
    cfg_path.write_text(text)
    (py_repo / ".seamspec/.local/trust.json").unlink()
    monkeypatch.setattr("seamspec.cli._interactive", lambda: True)
    result = runner.invoke(
        app, ["init", "--path", str(py_repo), "--no-claude-md", "--no-plugin", "--no-ci"], input="n\n"
    )
    assert "\x1b" not in result.output and 'X="a\\u001b[2J\\nAll good. y"' in result.output
    assert "[pytest] pytest -c .seamspec/pytest.ini" in result.output  # plain tokens print as they are


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
    assert 'PATH="${PATH:+$PATH:}$HOME/.local/bin"' in hook.read_text()  # GUI git clients, no empty entry (§16.4)
    assert git_hooks.install_pre_commit(gated_repo).status == "unchanged"


def test_hook_skips_a_branch_without_seamspec_but_not_a_deleted_config(gated_repo: Path) -> None:
    """Dogfooding #6: the hook lives in .git/hooks and so runs on every branch."""
    root = gated_repo
    assert commit(root, "set up seamspec").returncode == 0
    git(root, "switch", "-q", "--orphan", "no-seamspec")  # a branch that never had SeamSpec
    shutil.rmtree(root / ".seamspec", ignore_errors=True)  # what's left is ignored local state
    (root / "README.md").write_text("hello\n")
    skipped = commit(root, "unrelated work")
    assert skipped.returncode == 0 and "not set up on this branch" in skipped.stderr
    git(root, "switch", "-q", "-f", "main")
    shutil.rmtree(root / ".seamspec")  # config in HEAD, deleted here: the gate must still run and fail
    blocked = commit(root, "drop seamspec")
    assert blocked.returncode != 0 and "not set up on this branch" not in blocked.stderr


def test_hook_fails_closed_when_git_is_missing(tmp_path: Path) -> None:
    """Without git the hook can't tell an ungoverned branch from a deleted config: it must block."""
    hook = tmp_path / "pre-commit"
    hook.write_text(git_hooks.render_hook(""))
    no_git = tmp_path / "bin"
    no_git.mkdir()
    result = subprocess.run(
        ["/bin/sh", str(hook)], cwd=tmp_path, capture_output=True, text=True,
        env={"PATH": str(no_git), "HOME": str(tmp_path / "home")},
    )  # fmt: skip
    assert result.returncode == 1 and "git not found" in result.stderr


def test_hook_on_a_first_commit_without_seamspec_passes(tmp_path: Path) -> None:
    """No HEAD yet and no config: nothing to check (not a git failure)."""
    git(tmp_path, "init", "-q", "-b", "main")
    hook = tmp_path / "pre-commit"
    hook.write_text(git_hooks.render_hook(""))
    result = subprocess.run(["/bin/sh", str(hook)], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0 and "not set up on this branch" in result.stderr


def test_scripted_init_keeps_an_earlier_consent(py_repo: Path) -> None:
    """Dogfooding #7: re-running init with no terminal and no flag must not record a "no" nobody gave."""
    store = Store(py_repo)
    assert trust.consent_given(store)
    result = runner.invoke(app, ["init", "--path", str(py_repo), "--no-claude-md", "--no-plugin", "--no-ci"])
    assert result.exit_code == 0 and "no consent asked" in result.output
    assert trust.consent_given(store) and trust.execution_permitted(store, load_config(py_repo))[0]


def test_scripted_init_of_a_new_repo_records_nothing(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("")
    result = runner.invoke(app, ["init", "--path", str(tmp_path), "--no-claude-md", "--no-plugin", "--no-ci"])
    assert result.exit_code == 0 and load_config(tmp_path).mode == "advisory"
    assert not (tmp_path / ".seamspec/.local/consent.json").exists()


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
    passed = runner.invoke(app, ["verify", "--proposed", good])
    assert passed.exit_code == 0 and "staged" not in passed.output  # it ran the files on disk (rehearsal, 2026-10-24)
    out = runner.invoke(app, ["verify", "--proposed", bad])
    assert out.exit_code == 1 and f"[FAIL] {bad}" in out.output and "stage it again" not in out.output
    # A plain `seamspec verify` keeps the runner's output and ends with the short block (dogfooding #11).
    assert out.output.index("[FAIL]") < out.output.index("1 rule fails:") < out.output.index("line 2: assert False")
    assert "commit blocked" not in out.output and "Full test output" not in out.output
    assert not list((in_repo / ".seamspec/tests").glob("test_inv_*.py"))
    assert Store(in_repo).get(good).status == InvStatus.PROPOSED
    locked_err = runner.invoke(app, ["verify", "--proposed", "inv_00000000"])
    assert locked_err.exit_code == 1


def test_verify_untrusted_fails_without_a_terminal(in_repo: Path) -> None:
    (in_repo / ".seamspec/.local/trust.json").unlink()
    result = runner.invoke(app, ["verify"])
    assert result.exit_code == 1 and "not trusted" in result.output
    assert runner.invoke(app, ["verify", "--ci"]).exit_code == 0  # CI policy is the consent


def test_a_clone_never_set_up_here_is_told_to_run_init(in_repo: Path) -> None:
    """A teammate's fresh clone: no consent and no trust on this machine. Their agent got a bare "not
    trusted" and skipped the check (second-actor benchmark, ADR-20261019-e2f8)."""
    for name in ("trust.json", "consent.json"):
        (in_repo / ".seamspec/.local" / name).unlink()
    result = runner.invoke(app, ["verify"])
    assert result.exit_code == 1 and "Run `seamspec init` in a terminal" in result.output
    assert "Agents: tell the user this" in result.output and "CI still checks the rules" in result.output


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


# --- mode changes through the CLI (ADR-20261007-1b4c) ----------------------------------------------


def test_lowering_the_mode_needs_a_human(gated_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", raising=False)
    refused = runner.invoke(app, ["init", "--path", str(gated_repo), "--mode", "advisory", "--no-plugin", "--no-ci"])
    assert refused.exit_code == 1 and "a human must do it" in refused.output
    assert load_config(gated_repo).mode == "enforced"
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")  # stands in for a person at a terminal
    ok = runner.invoke(app, ["init", "--path", str(gated_repo), "--mode", "advisory", "--no-plugin", "--no-ci"])
    assert ok.exit_code == 0 and "enforced → advisory" in ok.output and "removed" in ok.output
    assert load_config(gated_repo).mode == "advisory"


def test_gate_in_advisory_mode_runs_nothing(gated_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")
    runner.invoke(app, ["init", "--path", str(gated_repo), "--mode", "advisory", "--no-plugin", "--no-ci"])
    (gated_repo / ".seamspec/.local/trust.json").unlink()  # even an untrusted clone: nothing runs
    monkeypatch.chdir(gated_repo)
    result = runner.invoke(app, ["verify", "--all", "--gate"])
    assert result.exit_code == 0 and "advisory mode" in result.output


def test_lowering_strict_to_enforced_needs_no_consent_and_keeps_it(
    gated_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review of #36: lowering was treated like raising (blocked without consent) and re-asked for consent."""
    from seamspec.installers import scaffold

    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")
    scaffold.init(gated_repo, mode="strict", auto_run=True, claude_md=False)
    consent = (gated_repo / ".seamspec/.local/consent.json").read_text()
    monkeypatch.setattr("seamspec.cli._interactive", lambda: True)
    result = runner.invoke(app, ["init", "--path", str(gated_repo), "--mode", "enforced", "--no-plugin", "--no-ci",
                                 "--no-claude-md"], input="y\n")  # only the "Lower the mode?" question  # fmt: skip
    assert result.exit_code == 0, result.output
    assert "Allow automatic test runs" not in result.output and "strict → enforced" in result.output
    assert load_config(gated_repo).mode == "enforced"
    assert (gated_repo / ".seamspec/.local/consent.json").read_text() == consent  # untouched


def test_lowering_to_advisory_keeps_this_machines_consent(gated_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")
    consent = (gated_repo / ".seamspec/.local/consent.json").read_text()
    runner.invoke(app, ["init", "--path", str(gated_repo), "--mode", "advisory", "--no-plugin", "--no-ci"])
    assert load_config(gated_repo).mode == "advisory"
    assert (gated_repo / ".seamspec/.local/consent.json").read_text() == consent  # no "no" nobody gave


def test_declining_consent_names_the_real_mode(py_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (py_repo / ".seamspec/.local/consent.json").unlink()
    monkeypatch.setattr("seamspec.cli._interactive", lambda: True)
    result = runner.invoke(app, ["init", "--path", str(py_repo), "--no-claude-md", "--no-plugin", "--no-ci"],
                           input="n\n")  # fmt: skip
    assert "off on this machine (the repository's mode is enforced)" in result.output
    assert "(advisory mode)" not in result.output
