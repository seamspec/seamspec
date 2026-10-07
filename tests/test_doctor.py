"""`seamspec doctor` and `doctor --ci` (SPEC §16.5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from seamspec.cli import app
from seamspec.core import doctor, lifecycle
from seamspec.core.config import load_config
from seamspec.core.store import Store

from .conftest import git
from .test_lifecycle import propose

runner = CliRunner()


@pytest.fixture
def locked_repo(git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    """A repo with one LOCKED rule, committed: the base for forward-only checks."""
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")
    inv_id = propose(git_repo)["id"]
    lifecycle.approve(Store(git_repo), load_config(git_repo), inv_id)
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-q", "--no-verify", "-m", "lock a rule")
    git(git_repo, "tag", "base")
    return git_repo, inv_id


def errors(report: doctor.DoctorReport, check: str | None = None) -> list[str]:
    return [f.message for f in report.findings if f.level == "error" and (check is None or f.check == check)]


def test_healthy_repo_is_clean(locked_repo: tuple[Path, str]) -> None:
    root, _ = locked_repo
    local = doctor.run(root)
    assert local.ok, local.findings
    ci = doctor.run(root, ci=True, base_ref="base")
    assert ci.ok and "None." in (ci.summary or "")


def test_broken_record_is_named(locked_repo: tuple[Path, str]) -> None:
    root, _ = locked_repo
    (root / ".seamspec/invariants/inv_deadbeef.json").write_text('{"id": "inv_deadbeef"}')
    msgs = errors(doctor.run(root), "schema")
    assert msgs and msgs[0].startswith(".seamspec/invariants/inv_deadbeef.json")


def test_tampered_harness_fails_integrity(locked_repo: tuple[Path, str]) -> None:
    root, inv_id = locked_repo
    harness = root / Store(root).get(inv_id).verification.harness_path
    harness.write_text(harness.read_text() + "\n# tweaked\n")
    assert any(inv_id in m for m in errors(doctor.run(root), "integrity"))


def test_changed_runner_config_is_an_error(locked_repo: tuple[Path, str]) -> None:
    root, _ = locked_repo
    ini = root / ".seamspec/pytest.ini"
    ini.write_text(ini.read_text() + "addopts = -p no:warnings\n")
    assert errors(doctor.run(root), "runner config")


# --- forward-only (CI) -----------------------------------------------------------------------------


def test_editing_a_locked_rule_and_its_hash_is_caught_in_ci(locked_repo: tuple[Path, str]) -> None:
    """An agent that rewrites the test *and* its recorded hash passes the integrity check; CI must not."""
    root, inv_id = locked_repo
    store = Store(root)
    inv = store.get(inv_id)
    harness = root / inv.verification.harness_path
    harness.write_text(harness.read_text().replace("<= 30", "<= 60"))
    from seamspec.core.hashing import sha256_file

    inv.verification.harness_sha256 = sha256_file(harness)
    store.save(inv)
    report = doctor.run(root, ci=True, base_ref="base")
    assert any("verification changed without a supersede" in m for m in errors(report, "forward-only"))
    assert any("changed without a supersede" in m for m in errors(report, "harness protection"))


def test_deleting_or_moving_back_a_locked_rule_is_caught(locked_repo: tuple[Path, str]) -> None:
    root, inv_id = locked_repo
    path = root / f".seamspec/invariants/{inv_id}.json"
    data = json.loads(path.read_text())
    data.update(status="PROPOSED", approved_at=None, approved_by=None)
    path.write_text(json.dumps(data))
    assert any("moved back from LOCKED to PROPOSED" in m for m in errors(doctor.run(root, ci=True, base_ref="base")))
    path.unlink()
    assert any("record was deleted" in m for m in errors(doctor.run(root, ci=True, base_ref="base")))


def test_supersede_passes_and_is_listed_in_the_retirement_summary(locked_repo: tuple[Path, str]) -> None:
    root, inv_id = locked_repo
    store, cfg = Store(root), load_config(root)
    lifecycle.supersede(store, cfg, inv_id, reason="cap is now 60s")
    report = doctor.run(root, ci=True, base_ref="base")
    assert report.ok, report.findings
    assert f"`{inv_id}`" in report.summary and "LOCKED → SUPERSEDED" in report.summary


def test_new_dead_ends_and_config_changes_are_listed(locked_repo: tuple[Path, str]) -> None:
    root, _ = locked_repo
    store, cfg = Store(root), load_config(root)
    de = lifecycle.log_dead_end(store, cfg, scope_paths=["src/**"], approach="A thread pool for retries.",
                                failure_symptom="It deadlocked.", source="manual")  # fmt: skip
    prints = root / ".seamspec/fingerprints.json"
    prints.write_text(json.dumps({**json.loads(prints.read_text()), ".seamspec/pytest.ini": "0" * 64}))
    summary = doctor.run(root, ci=True, base_ref="base").summary or ""
    assert f"`{de['id']}`" in summary and "(none) → ACTIVE" in summary
    assert "`.seamspec/pytest.ini`" in summary


def test_unreadable_base_says_how_to_fix_it(locked_repo: tuple[Path, str]) -> None:
    root, _ = locked_repo
    report = doctor.run(root, ci=True, base_ref="origin/nope")
    assert any("fetch-depth: 0" in m for m in errors(report, "forward-only")) and report.summary is None


def test_default_base_follows_github(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_BASE_REF", "main")
    assert doctor.default_base() == "origin/main"
    monkeypatch.delenv("GITHUB_BASE_REF")
    assert doctor.default_base() == "HEAD~1"


# --- local-only warnings ---------------------------------------------------------------------------


def test_local_warnings(locked_repo: tuple[Path, str]) -> None:
    root, _ = locked_repo
    (root / ".claude").mkdir(exist_ok=True)
    (root / ".claude/settings.local.json").write_text('{"permissions": {"allow": ["Bash(seamspec verify:*)"]}}')
    (root / "CLAUDE.md").write_text("# Project\n")  # no SeamSpec block
    report = doctor.run(root)
    checks = {f.check for f in report.findings if f.level == "warning"}
    assert {"allowlist", "directive"} <= checks
    assert report.ok  # warnings never fail


def test_cli_exit_codes_and_step_summary(locked_repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch,
                                         tmp_path: Path) -> None:  # fmt: skip
    root, inv_id = locked_repo
    monkeypatch.chdir(root)
    step = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step))
    ok = runner.invoke(app, ["doctor", "--ci", "--base", "base"])
    assert ok.exit_code == 0 and "✓ forward-only" in ok.output and step.read_text().startswith("## SeamSpec")
    (root / f".seamspec/invariants/{inv_id}.json").unlink()
    bad = runner.invoke(app, ["doctor", "--ci", "--base", "base", "--json"])
    assert bad.exit_code == 1 and json.loads(bad.output)["ok"] is False
