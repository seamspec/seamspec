"""Benchmark tasks and conditions (ADR-20261006-c8b9).

Each task lives in `bench/tasks/<id>/`:
- `template/`: the repo the agent works on;
- `task.json`: rules, the known dead end, the session prompts, and the unrelated or outdated
  decision records that surround the real ones in condition F (`adr_noise`);
- `rules/`: the visible rule tests (enforced in B, C and D);
- `oracle/`: the hidden tests that score every condition. The agent never sees them.

TypeScript tests import from `{{SRC}}/prices`; `rule_source()` fills in the path for where the
test is installed. Python tests find `src/` themselves.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

TASKS_DIR = Path(__file__).resolve().parents[1] / "tasks"
TASK_IDS = ("t1_queue", "t2_prices", "t3_export")
CONDITIONS = ("A", "B", "C", "D", "E", "F", "G", "H")
PASS_BAR_CONDITIONS = ("A", "B", "C", "D")  # E and F are read separately (ADR-20261007-e1a7, ADR-20261013-9d41)
CONDITION_NAMES = {
    "A": "baseline (no SeamSpec)",
    "B": "SeamSpec advisory",
    "C": "SeamSpec enforced",
    "D": "plain tests + Stop hook",
    "E": "rules written in CLAUDE.md",
    "F": "decisions in ADRs only",
    "G": "many rules written in CLAUDE.md",
    "H": "SeamSpec enforced, many rules",
}
USES_PLUGIN = ("B", "C", "H")  # conditions that load the SeamSpec plugin


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    assertion: str
    scope: tuple[str, ...]
    file: str  # file name in rules/ and oracle/


@dataclass(frozen=True)
class DeadEnd:
    approach: str
    symptom: str
    scope: tuple[str, ...]
    short: str = ""  # a few words, for a decision record's title (condition F)


@dataclass(frozen=True)
class NoiseAdr:
    """A decision record that is not one of the rules: unrelated, or an older decision a rule replaced."""

    title: str
    status: str  # Accepted | Superseded
    body: str
    superseded_by: str | None = None  # a rule id


@dataclass(frozen=True)
class Task:
    id: str
    language: str  # python | typescript
    runner: str  # pytest | vitest
    rules: tuple[Rule, ...]
    dead_end: DeadEnd
    sessions: tuple[tuple[str, ...], ...]
    dir: Path
    adr_noise: tuple[NoiseAdr, ...] = ()  # condition F

    @property
    def template(self) -> Path:
        return self.dir / "template"

    def rule_source(self, rule: Rule, kind: str, depth: int) -> str:
        """A rule or oracle test's code, for a file `depth` folders below the repo root."""
        text = (self.dir / kind / rule.file).read_text(encoding="utf-8")
        return text.replace("{{SRC}}", "/".join([".."] * depth) + "/src")


def load(task_id: str) -> Task:
    d = TASKS_DIR / task_id
    data = json.loads((d / "task.json").read_text(encoding="utf-8"))
    rules = tuple(Rule(r["id"], r["title"], r["assertion"], tuple(r["scope"]), r["file"]) for r in data["rules"])
    de = data["dead_end"]
    return Task(
        id=data["id"],
        language=data["language"],
        runner=data["runner"],
        rules=rules,
        dead_end=DeadEnd(de["approach"], de["symptom"], tuple(de["scope"]), de.get("short", "")),
        sessions=tuple(tuple(s) for s in data["sessions"]),
        dir=d,
        adr_noise=tuple(
            NoiseAdr(n["title"], n["status"], n["body"], n.get("superseded_by")) for n in data.get("adr_noise", [])
        ),
    )
