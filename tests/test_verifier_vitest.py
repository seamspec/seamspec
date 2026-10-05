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
