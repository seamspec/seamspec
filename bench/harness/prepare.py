"""Set up one run's working copy of a task for one condition (ADR-20261006-c8b9).

| Condition | What carries the rules across sessions |
|---|---|
| A | nothing (session 1's prompt states them; later sessions don't) |
| B | SeamSpec advisory: ledger with the rules LOCKED and the dead end, CLAUDE.md block, MCP |
| C | SeamSpec enforced: B plus the plugin's hooks and the git pre-commit gate |
| D | the same rule tests in tests/rules plus a Stop hook that runs them (no SeamSpec) |
| E | the rules and the dead end as plain notes in CLAUDE.md, as a careful person would write them |
| F | the rules and the dead end as decision records in docs/adr/, among unrelated and outdated ones |

The rules start already in place, as if a human approved them in an earlier week. Working
copies live outside this repository (SeamSpec looks for `.seamspec/` in parent folders).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .tasks import Task

CACHE = Path(os.environ.get("SEAMSPEC_BENCH_CACHE", str(Path.home() / ".cache" / "seamspec-bench")))
PYTEST_PIN = "pytest==9.1.1"
START_TAG = "bench-start"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "Bench Owner",
    "GIT_AUTHOR_EMAIL": "owner@bench.invalid",
    "GIT_COMMITTER_NAME": "Bench Owner",
    "GIT_COMMITTER_EMAIL": "owner@bench.invalid",
}


@dataclass
class Prepared:
    work: Path
    condition: str
    rule_test_paths: list[str]  # repo-relative files the agent must not tamper with (none in A)


def _run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env={**os.environ, **(env or {})})
    if out.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed in {cwd}:\n{out.stdout}\n{out.stderr}")
    return out.stdout


def git(work: Path, *args: str) -> str:
    return _run(["git", *args], work, GIT_ENV)


def node_modules() -> Path:
    """One shared vitest install (pinned by the T2 template's lockfile), linked into each run."""
    target = CACHE / "t2-node"
    if not (target / "node_modules/.bin/vitest").exists():
        target.mkdir(parents=True, exist_ok=True)
        template = Path(__file__).resolve().parents[1] / "tasks/t2_prices/template"
        for name in ("package.json", "package-lock.json"):
            shutil.copy(template / name, target / name)
        _run(["npm", "ci", "--silent"], target)
    return target / "node_modules"


def _toolchain(task: Task, work: Path) -> None:
    if task.language == "python":
        _run(["uv", "venv", "-q", "--python", "3.12", str(work / ".venv")], work)
        _run(["uv", "pip", "install", "-q", "--python", str(work / ".venv/bin/python"), PYTEST_PIN], work)
    else:
        (work / "node_modules").symlink_to(node_modules(), target_is_directory=True)


def _seed_ledger(task: Task, work: Path) -> list[str]:
    """LOCKED rules and the dead end, approved 'in an earlier week'. Returns the rule test paths."""
    from seamspec.core import lifecycle
    from seamspec.core.config import load_config
    from seamspec.core.store import Store

    store, cfg = Store(work), load_config(work)
    depth = 2  # vitest harness_dir is tests/seamspec/; Python rule tests find src/ themselves
    os.environ["SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE"] = "1"  # the benchmark owner approves them
    try:
        paths = []
        for rule in task.rules:
            proposal = lifecycle.propose_invariant(
                store,
                cfg,
                title=rule.title,
                assertion=rule.assertion,
                scope_paths=list(rule.scope),
                runner=task.runner,
                harness_code=task.rule_source(rule, "rules", depth),
                origin_text=f"Benchmark rule {rule.id}, agreed with the team in an earlier week.",
                origin_type="manual",
                by_human=True,
            )
            lifecycle.approve(store, cfg, proposal["id"], actor="Bench Owner <owner@bench.invalid>")
            paths.append(store.get(proposal["id"]).verification.harness_path)
        lifecycle.log_dead_end(
            store,
            cfg,
            scope_paths=list(task.dead_end.scope),
            approach=task.dead_end.approach,
            failure_symptom=task.dead_end.symptom,
            source="manual",
        )
    finally:
        os.environ.pop("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", None)
    return paths


def _plain_tests(task: Task, work: Path) -> list[str]:
    rules_dir = work / "tests" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for rule in task.rules:
        (rules_dir / rule.file).write_text(task.rule_source(rule, "rules", 2), encoding="utf-8")
        paths.append(f"tests/rules/{rule.file}")
    hook = Path(__file__).resolve().parent / "plain_stop_hook.py"
    settings = {"hooks": {"Stop": [{"hooks": [{"type": "command", "timeout": 300,
                "command": f'"{sys.executable}" "{hook}" {task.runner}'}]}]}}  # fmt: skip
    (work / ".claude").mkdir(exist_ok=True)
    (work / ".claude/settings.json").write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return paths


def notes_text(task: Task) -> str:
    """Condition E: the agreements as a careful teammate would write them in CLAUDE.md. Same facts
    as the ledger gives B and C, plus the same "ask first" habit SeamSpec's directive asks for."""
    lines = ["# Team agreements", "", "Agreed with the team; other services and people rely on them:", ""]
    lines += [f"- **{rule.title}.** {rule.assertion}" for rule in task.rules]
    lines += ["", "## Tried before and failed", "", f"- {task.dead_end.approach} {task.dead_end.symptom}", ""]
    lines += ["If a request would break one of these agreements, don't change it on your own: say which",
              "agreement it conflicts with and ask the user first.", ""]  # fmt: skip
    return "\n".join(lines)


ADR_DIR = "docs/adr"


def _slug(title: str) -> str:
    keep = "".join(c.lower() if c.isalnum() else "-" for c in title)
    return "-".join(part for part in keep.split("-") if part)[:60]


def adr_files(task: Task) -> dict[str, str]:
    """Condition F (ADR-20261013-9d41): the agreements as decision records, the way many teams keep
    them. Older records come first, one of them an earlier decision that a rule later replaced, so
    reading only part of the folder can mislead. Same facts as E's notes; no "ask first" line and no
    pointer from anywhere else in the repo: whether the agent looks is what F measures."""
    entries: list[dict] = [  # (title, status, sections, key) in the order they were decided
        {
            "title": n.title,
            "status": n.status,
            "sections": [("Context and decision", n.body)],
            "replaced_by": n.superseded_by,
        }
        for n in task.adr_noise
    ]
    number_of_rule: dict[str, int] = {}
    for rule in task.rules:
        entries.append({
            "title": rule.title,
            "status": "Accepted",
            "sections": [("Decision", rule.assertion),
                         ("Consequences", "Agreed with the team; other services and people rely on it.")],
            "rule": rule.id,
        })  # fmt: skip
        number_of_rule[rule.id] = len(entries)
    entries.append({
        "title": "Rejected: " + (task.dead_end.short or task.dead_end.approach.rstrip(".")),
        "status": "Rejected",
        "sections": [("What we tried", task.dead_end.approach), ("What happened", task.dead_end.symptom)],
    })  # fmt: skip

    files: dict[str, str] = {}
    index = ["# Decision records", "", "| No. | Decision | Status |", "|---|---|---|"]
    for number, entry in enumerate(entries, start=1):
        name = f"{number:04d}-{_slug(entry['title'])}.md"
        status = entry["status"]
        if entry.get("replaced_by"):
            status = f"Superseded by {number_of_rule[entry['replaced_by']]:04d}"
        lines = [f"# {number:04d}. {entry['title']}", "", f"- Status: {status}",
                 f"- Date: 2026-{min(number, 9):02d}-{10 + number % 18:02d}"]  # fmt: skip
        replaces = [
            n for n, e in enumerate(entries, start=1) if e.get("replaced_by") and e["replaced_by"] == entry.get("rule")
        ]
        if replaces:
            lines.append("- Supersedes: " + ", ".join(f"{n:04d}" for n in replaces))
        for heading, text in entry["sections"]:
            lines += ["", f"## {heading}", "", text]
        files[f"{ADR_DIR}/{name}"] = "\n".join(lines) + "\n"
        index.append(f"| {number:04d} | [{entry['title']}]({name}) | {status} |")
    files[f"{ADR_DIR}/README.md"] = "\n".join(index) + "\n"
    return files


def prepare(task: Task, condition: str, work: Path) -> Prepared:
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(task.template, work)
    git(work, "init", "-q", "-b", "main")
    _toolchain(task, work)

    rule_paths: list[str] = []
    if condition in ("B", "C"):
        from seamspec.installers import scaffold

        scaffold.init(work, mode="advisory" if condition == "B" else "enforced", auto_run=condition == "C",
                      actor="Bench Owner <owner@bench.invalid>")  # fmt: skip
        rule_paths = _seed_ledger(task, work)
    elif condition == "D":
        rule_paths = _plain_tests(task, work)
    elif condition == "E":
        (work / "CLAUDE.md").write_text(notes_text(task), encoding="utf-8")
    elif condition == "F":
        for rel, text in adr_files(task).items():
            (work / rel).parent.mkdir(parents=True, exist_ok=True)
            (work / rel).write_text(text, encoding="utf-8")
    elif condition != "A":
        raise ValueError(f"unknown condition {condition!r}")

    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", f"Start: {task.id}, condition {condition}")  # C: through the gate
    git(work, "tag", START_TAG)
    return Prepared(work, condition, rule_paths)
