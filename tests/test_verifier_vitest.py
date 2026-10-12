"""Verifier against real vitest runs (SPEC §12.3, §12A.4).

Needs the pinned vitest install in tests/fixtures/ts_repo:  npm ci --prefix tests/fixtures/ts_repo
Skipped when it's missing, unless SEAMSPEC_REQUIRE_VITEST=1 (set in CI), which turns the skip into a failure.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from seamspec.core import verifier
from seamspec.core.config import load_config
from seamspec.installers import scaffold

from .verify_helpers import write_locked

FIXTURE_MODULES = Path(__file__).parent / "fixtures" / "ts_repo" / "node_modules"


@pytest.fixture
def ts_repo(tmp_path: Path) -> Path:
    if not (FIXTURE_MODULES / "vitest").is_dir() or shutil.which("npx") is None:
        if os.environ.get("SEAMSPEC_REQUIRE_VITEST") == "1":
            pytest.fail("vitest fixture missing: run `npm ci --prefix tests/fixtures/ts_repo`")
        pytest.skip("vitest fixture not installed (npm ci --prefix tests/fixtures/ts_repo)")
    (tmp_path / "package.json").write_text('{"type": "module", "devDependencies": {"vitest": "3.2.7"}}')
    (tmp_path / "node_modules").symlink_to(FIXTURE_MODULES, target_is_directory=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/queue.ts").write_text("export const backoffDelay = (n: number) => Math.min(0.1 * 2 ** n, 30);\n")
    # A project config whose setup would throw: SeamSpec's own config must keep it out (§12.3).
    (tmp_path / "setup.ts").write_text('throw new Error("project setupFiles must not run for locked tests");\n')
    (tmp_path / "vitest.config.ts").write_text('export default { test: { setupFiles: ["./setup.ts"] } };\n')
    scaffold.init(tmp_path)
    assert list(load_config(tmp_path).runners) == ["vitest"]
    return tmp_path


PASS = (
    'import { test, expect } from "vitest";\n'
    'import { backoffDelay } from "../../src/queue";\n'
    'test("cap", () => { expect(backoffDelay(100)).toBeLessThanOrEqual(30); });\n'
)
FAIL = 'import { test, expect } from "vitest";\ntest("fails", () => { expect(1).toBe(2); });\n'
BROKEN = 'import { test } from "vitest";\nimport { nope } from "../../src/missing";\ntest("x", () => { nope(); });\n'
SKIPPED = 'import { test } from "vitest";\ntest.skip("s", () => {});\n'


def test_vitest_end_to_end_attribution(ts_repo: Path) -> None:
    cfg = load_config(ts_repo)
    invs = [
        write_locked(ts_repo, cfg, "inv_00000001", PASS, runner="vitest"),
        write_locked(ts_repo, cfg, "inv_00000002", FAIL, runner="vitest"),
        write_locked(ts_repo, cfg, "inv_00000003", BROKEN, runner="vitest"),
        write_locked(ts_repo, cfg, "inv_00000004", SKIPPED, runner="vitest"),
    ]
    report = verifier.run(ts_repo, cfg, invs)
    assert report.failing_ids == ["inv_00000002", "inv_00000003", "inv_00000004"], report.results[0].output
    assert not report.config_failures


def test_vitest_passes_with_project_setup_ignored(ts_repo: Path) -> None:
    cfg = load_config(ts_repo)
    inv = write_locked(ts_repo, cfg, "inv_00000001", PASS, runner="vitest")
    report = verifier.run(ts_repo, cfg, [inv])
    assert report.passed, report.results[0].output


def test_pre_commit_blocks_a_typescript_regression(ts_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Week 2 exit criterion, TypeScript half: propose → approve → pre-commit blocks a regression."""
    import subprocess

    from typer.testing import CliRunner

    from seamspec.cli import app
    from seamspec.core import lifecycle
    from seamspec.core.store import Store

    from .conftest import git

    root = ts_repo
    (root / ".gitignore").write_text((root / ".gitignore").read_text() + "node_modules\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Maya Rao")
    git(root, "config", "user.email", "maya@example.com")
    result = CliRunner().invoke(app, ["init", "--path", str(root), "--accept-auto-run"])
    assert result.exit_code == 0 and "git pre-commit hook" in result.output, result.output

    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")
    store, cfg = Store(root), load_config(root)
    out = lifecycle.propose_invariant(
        store, cfg, title="Retry delay is capped", assertion="Retry delay never exceeds 30 seconds.",
        scope_paths=["src/**"], runner="vitest", harness_code=PASS, origin_text="cap at 30s",
    )  # fmt: skip
    lifecycle.approve(store, cfg, out["id"])
    assert (root / f"tests/seamspec/{out['id']}.test.ts").is_file()

    env = {k: v for k, v in os.environ.items() if k != "SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE"}

    def commit(msg: str) -> subprocess.CompletedProcess[str]:
        git(root, "add", "-A")
        return subprocess.run(["git", "commit", "-q", "-m", msg], cwd=root, capture_output=True, text=True, env=env)

    assert commit("lock").returncode == 0
    (root / "src/queue.ts").write_text("export const backoffDelay = (n: number) => 0.1 * 2 ** n;\n")
    blocked = commit("remove the cap")
    assert blocked.returncode != 0 and "SeamSpec: commit blocked." in blocked.stderr, blocked.stderr
    assert f"  {out['id']} · " in blocked.stderr and "    line " in blocked.stderr, blocked.stderr


def test_red_green_in_a_typescript_repo(ts_repo: Path) -> None:
    """The HEAD worktree has no node_modules of its own; red-green links the project's in (§11.4)."""
    from seamspec.core import lifecycle, redgreen
    from seamspec.core.store import Store

    from .conftest import git

    (ts_repo / ".gitignore").write_text((ts_repo / ".gitignore").read_text() + "node_modules\n")
    git(ts_repo, "init", "-q", "-b", "main")
    git(ts_repo, "add", "-A")
    git(ts_repo, "commit", "-q", "-m", "init")
    (ts_repo / "src/queue.ts").write_text(
        "export const backoffDelay = (n: number) => Math.min(0.1 * 2 ** n, 30);\n"
        "export const jitter = (x: number) => x / 2;\n"
    )
    jitter = 'import { test, expect } from "vitest";\nimport { jitter } from "../../src/queue";\ntest("halves", () => { expect(jitter(10)).toBe(5); });\n'  # noqa: E501
    store, cfg = Store(ts_repo), load_config(ts_repo)
    common = {"scope_paths": ["src/**"], "runner": "vitest", "origin_text": "x"}
    new = lifecycle.propose_invariant(
        store, cfg, title="Jitter halves", assertion="Jitter halves the delay.", harness_code=jitter, **common
    )
    old = lifecycle.propose_invariant(
        store, cfg, title="Cap", assertion="Retry delay never exceeds 30 seconds.", harness_code=PASS, **common
    )
    result = redgreen.check(store, cfg, store.get(new["id"]))
    assert result.verdict == "yes" and result.new_code and "is not a function" in result.detail  # dogfooding #9
    assert redgreen.check(store, cfg, store.get(old["id"])).verdict == "no"
    assert git(ts_repo, "worktree", "list").count("\n") == 1
