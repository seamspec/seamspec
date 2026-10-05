"""Runs invariant harnesses with configured runners (SPEC §12.2, §12A, §19.7).

Not a sandbox: harnesses and the project code they import run with the user's permissions.
What this module controls is *what* runs (argv from config, explicit harness paths), *how long*
(per-runner timeout inside one overall deadline, whole process group killed), *what it can see*
(scrubbed environment, no "under verification" flag) and *whether the result can be trusted*
(integrity hashes, runner config fingerprints, empty or all-skipped harnesses fail).
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from . import reports
from .config import Config, RunnerCfg
from .hashing import sha256_file, sha256_text
from .models import Invariant, InvStatus, utcnow
from .store import atomic_write

FINGERPRINTS_REL = Path(".seamspec") / "fingerprints.json"
LAST_VERIFY_REL = Path(".seamspec") / ".local" / "last_verify.json"
REPORTS_REL = Path(".seamspec") / ".local" / "reports"

# Everything else (AWS_*, GITHUB_TOKEN, *_API_KEY, PYTEST_ADDOPTS, ...) is dropped (§12.4.7).
BASE_ENV_KEYS = frozenset(
    {"PATH", "HOME", "USER", "LANG", "TERM", "TMPDIR", "SHELL", "SYSTEMROOT", "VIRTUAL_ENV", "PYTHONPATH", "NODE_PATH"}
)


@dataclass
class RunnerResult:
    runner: str
    invariant_ids: list[str]
    passed: bool
    output: str
    duration_s: float
    timed_out: bool = False
    incomplete: bool = False  # not run, or cut off, because the overall deadline was reached
    failed_ids: list[str] | None = None  # None = not attributed; the whole group counts as failing


@dataclass
class VerifyReport:
    passed: bool
    integrity_failures: list[str] = field(default_factory=list)  # "inv_x: harness modified ..."
    config_failures: list[str] = field(default_factory=list)  # runner config fingerprint mismatches
    results: list[RunnerResult] = field(default_factory=list)
    incomplete: bool = False  # deadline reached: an explicit outcome, never a silent pass

    @property
    def failing_ids(self) -> list[str]:
        ids = [msg.split(":", 1)[0] for msg in self.integrity_failures]
        for r in self.results:
            if not r.passed and not r.incomplete:
                ids.extend(r.failed_ids if r.failed_ids is not None else r.invariant_ids)
        return sorted(set(ids))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["failing_ids"] = self.failing_ids
        return data


def _truncate(text: str, limit: int) -> str:
    """Keep the head and the (usually more useful) tail of long output."""
    if len(text) <= limit:
        return text
    head = limit // 4
    tail = limit - head
    return f"{text[:head]}\n... [truncated {len(text) - limit} chars] ...\n{text[-tail:]}"


def check_integrity(root: Path, inv: Invariant) -> str | None:
    """LOCKED harness and assertion must match the hashes taken at approval."""
    if inv.status != InvStatus.LOCKED:
        return None
    harness = root / inv.verification.harness_path
    if not harness.is_file():
        return f"{inv.id}: harness missing ({inv.verification.harness_path})"
    if sha256_file(harness) != inv.verification.harness_sha256:
        return f"{inv.id}: harness modified since approval"
    if sha256_text(inv.assertion) != inv.verification.assertion_sha256:
        return f"{inv.id}: assertion modified since approval"
    return None


def read_fingerprints(root: Path) -> dict[str, str]:
    path = root / FINGERPRINTS_REL
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def current_fingerprints(root: Path, cfg: Config) -> dict[str, str]:
    """Hashes of every runner's config files as they are now. Nothing is written."""
    return {
        rel: sha256_file(root / rel)
        for runner in cfg.runners.values()
        for rel in runner.config_files
        if (root / rel).is_file()
    }


def check_fingerprints(root: Path, cfg: Config, confirmed: dict[str, str] | None = None) -> list[str]:
    """Runner config files must match what a human confirmed (§12.2). `approve` passes the hashes
    the human is confirming right now, so a failed approval writes nothing (§19.8)."""
    if confirmed is None:
        confirmed = read_fingerprints(root)
    problems = []
    for runner in cfg.runners.values():
        for rel in runner.config_files:
            f = root / rel
            actual = sha256_file(f) if f.is_file() else None
            if actual is None:
                problems.append(f"{rel}: runner config file is missing")
            elif actual != confirmed.get(rel):
                problems.append(f"{rel}: changed since it was last confirmed in `seamspec review`")
    return problems


def build_env(cfg: Config, environ: dict[str, str] | None = None) -> dict[str, str]:
    """Minimal environment for test runs (§12.4.7). Deliberately NO "under verification" flag:
    code must not be able to tell it is being checked."""
    source = os.environ if environ is None else environ
    allowed = BASE_ENV_KEYS | set(cfg.execution.env_passthrough)
    return {k: v for k, v in source.items() if k in allowed or k.startswith("LC_")}


def expand_argv(runner: RunnerCfg, invs: list[Invariant], report_path: Path) -> list[str]:
    """Build argv from config tokens. The only per-invariant values are harness paths that
    SeamSpec generated itself, never agent-supplied strings (§12.2)."""
    per_harness: list[str] = []
    seen: set[tuple[str, ...]] = set()
    for inv in invs:
        p = PurePosixPath(inv.verification.harness_path)
        values = {"path": str(p), "dir": f"./{p.parent}", "stem": p.stem, "id": inv.id}
        chunk = tuple(t.format_map(values) for t in runner.each)
        if chunk not in seen:
            seen.add(chunk)
            per_harness.extend(chunk)
    argv: list[str] = []
    for token in runner.cmd:
        if token in ("{each}", "{harnesses}"):
            argv.extend(per_harness)
        else:
            argv.append(token.replace("{report}", str(report_path)))
    return argv


def _kill_group(proc: subprocess.Popen[str]) -> None:
    """Kill the runner and everything it spawned (vitest workers, npx children, cargo)."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:  # pragma: no cover - Windows is best effort in v0.1
            proc.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):  # pipes held by an unkillable child
        proc.communicate(timeout=5)


def _invoke(
    root: Path, cfg: Config, name: str, runner: RunnerCfg, invs: list[Invariant], deadline: float | None
) -> RunnerResult:
    ids = [i.id for i in invs]
    budget = float(cfg.verify.timeout_seconds)
    if deadline is not None:
        budget = min(budget, deadline - time.monotonic())
        if budget <= 0:
            return RunnerResult(name, ids, False, "Not run: verification deadline reached.", 0.0, incomplete=True)

    report_path = root / REPORTS_REL / f"{name}.xml"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.unlink(missing_ok=True)  # never read a stale report
    argv = expand_argv(runner, invs, report_path)
    env = build_env(cfg) | {k: v.replace("{report}", str(report_path)) for k, v in runner.env.items()}

    start = time.monotonic()
    try:
        proc = subprocess.Popen(
            argv,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            env=env,
            start_new_session=True,
        )
    except FileNotFoundError:
        return RunnerResult(
            name, ids, False, f"Runner executable '{argv[0]}' not found. Install it or fix config.toml.", 0.0
        )
    try:
        stdout, stderr = proc.communicate(timeout=budget)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        cut_by_deadline = deadline is not None and time.monotonic() >= deadline - 0.5
        return RunnerResult(
            name,
            ids,
            False,
            f"Timed out after {budget:.0f}s; the runner and its child processes were stopped.",
            time.monotonic() - start,
            timed_out=True,
            incomplete=cut_by_deadline,
        )

    stdout = stdout or ""
    attributed: reports.Attribution | None = None
    if runner.report == "junit":
        attributed = reports.junit(report_path, ids)
    elif runner.report == "go-test-json":
        attributed, stdout = reports.go_test_json(stdout, ids)

    output = stdout + (("\n" + stderr) if stderr else "")
    if attributed is None:  # report = "none" or unusable report: exit code only
        passed, failed_ids = proc.returncode == 0, None
    else:
        failed, empty = attributed
        bad = failed | empty
        passed = proc.returncode == 0 and not bad
        failed_ids = sorted(bad) if bad else None  # nothing attributed on a failure = unknown
        if empty:
            output += "\nRan no tests, or skipped every test (counts as a failure): " + ", ".join(sorted(empty))
    output = _truncate(output, cfg.verify.max_output_chars)
    return RunnerResult(name, ids, passed, output, time.monotonic() - start, failed_ids=failed_ids)


def run(
    root: Path,
    cfg: Config,
    invariants: list[Invariant],
    deadline: float | None = None,
    fingerprints: dict[str, str] | None = None,
) -> VerifyReport:
    """Verify `invariants`. `deadline` is a time.monotonic() value: hooks pass
    now + verify.stop_deadline_seconds; pre-commit and CI pass None (no deadline, always the full set).
    `fingerprints` overrides the committed fingerprints.json (used by approve, §19.8)."""
    report = VerifyReport(passed=True)
    report.config_failures = check_fingerprints(root, cfg, fingerprints)

    runnable: list[Invariant] = []
    for inv in invariants:
        problem = check_integrity(root, inv)
        if problem:
            report.integrity_failures.append(problem)
        else:
            runnable.append(inv)

    by_runner: dict[str, list[Invariant]] = defaultdict(list)
    for inv in runnable:
        by_runner[inv.verification.runner].append(inv)

    for name, invs in by_runner.items():
        runner = cfg.runners.get(name)
        if runner is None:
            report.results.append(
                RunnerResult(name, [i.id for i in invs], False, f"Unknown runner '{name}' in config.toml", 0.0)
            )
            continue

        result = _invoke(root, cfg, name, runner, invs, deadline)
        # Fallback attribution (§12A.4): rerun each harness alone, while time remains.
        if (
            not result.passed
            and not result.timed_out
            and result.failed_ids is None
            and 1 < len(invs) <= cfg.verify.isolate_on_failure
        ):
            alone: list[str] = []
            for inv in invs:
                single = _invoke(root, cfg, name, runner, [inv], deadline)
                if single.incomplete:
                    alone = []  # out of time: keep the group result unattributed
                    break
                if not single.passed:
                    alone.append(inv.id)
            result.failed_ids = alone or None
        report.results.append(result)

    report.incomplete = any(r.incomplete for r in report.results)
    report.passed = (
        not report.integrity_failures
        and not report.config_failures
        and not report.incomplete
        and all(r.passed for r in report.results)
    )
    return report


def save_last(root: Path, report: VerifyReport) -> None:
    """Record the latest result for `seamspec status` and the Stop hook (§12.2)."""
    data = {"at": utcnow().isoformat().replace("+00:00", "Z"), **report.to_dict()}
    atomic_write(root / LAST_VERIFY_REL, json.dumps(data, indent=2) + "\n")
