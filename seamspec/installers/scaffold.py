"""`seamspec init` scaffolding (SPEC §9.1, §12.3, §12A.7, §15).

Merges into existing files and never clobbers: an existing config.toml or runner config is kept
as is, `.gitignore` only gains missing lines, and CLAUDE.md only changes between the markers.
Hooks, the Claude Code plugin, pre-commit, CI and the auto-run consent screen are installed by
later steps (roadmap weeks 2-4, SPEC §22).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Literal

from ..core.config import load_config, parse_config
from ..core.root import CONFIG_REL
from ..core.runners import V01_PRESETS, Detection, detect, preset_toml
from ..core.store import atomic_write
from . import directive

Mode = Literal["advisory", "enforced", "strict"]

LEDGER_DIRS = ("invariants", "dead_ends", "adrs", "proposed", "retired", ".local")
GITIGNORE_LINES = (".seamspec/.local/",)
RUNNER_CONFIG_TEMPLATES = {
    ".seamspec/pytest.ini": "pytest.ini",
    ".seamspec/vitest.config.mjs": "vitest.config.mjs",
}


@dataclass
class InitReport:
    root: Path
    mode: Mode
    detection: Detection
    actions: list[tuple[str, str]] = field(default_factory=list)  # (path, created|updated|unchanged|kept)

    def add(self, path: str, what: str) -> None:
        self.actions.append((path, what))


def _template(name: str) -> str:
    return files("seamspec.templates").joinpath(name).read_text("utf-8")


def render_config(mode: Mode, runners: list[str]) -> str:
    if runners:
        tables = "\n".join(preset_toml(r) for r in runners)
    else:
        commented = "\n".join(preset_toml(r) for r in V01_PRESETS)
        tables = "# No supported language detected. Uncomment the runner you need:\n" + "\n".join(
            f"# {ln}" if ln else "#" for ln in commented.splitlines()
        )
    strict = mode == "strict"
    text = (
        _template("config.toml")
        .replace("{{mode}}", mode)
        .replace("{{runners}}", tables.rstrip("\n"))
        .replace(
            "{{hooks_extra}}",
            "fail_closed = true             # strict mode default\n"
            if strict
            else "fail_closed = false            # strict mode defaults to true\n",
        )
        .replace(
            "{{execution_extra}}",
            'trust_level = "harness"        # strict mode default (v0.2)\n'
            if strict
            else 'trust_level = "runners"        # runners | harness\n',
        )
    )
    parse_config(text, "generated config.toml")  # never write a config SeamSpec itself can't load
    return text


def _write_if_missing(root: Path, rel: str, text: str, report: InitReport) -> None:
    path = root / rel
    if path.exists():
        report.add(rel, "kept")
        return
    atomic_write(path, text)
    report.add(rel, "created")


def _merge_gitignore(root: Path, report: InitReport) -> None:
    path = root / ".gitignore"
    old = path.read_text(encoding="utf-8") if path.is_file() else ""
    present = {ln.strip() for ln in old.splitlines()}
    missing = [ln for ln in GITIGNORE_LINES if ln not in present]
    if not missing:
        report.add(".gitignore", "unchanged")
        return
    sep = "" if not old or old.endswith("\n") else "\n"
    block = "\n# SeamSpec machine-local state\n" + "\n".join(missing) + "\n"
    atomic_write(path, old + sep + (block if old else block.lstrip("\n")))
    report.add(".gitignore", "updated" if old else "created")


def init(root: Path, mode: Mode = "enforced", claude_md: bool = True) -> InitReport:
    root = root.resolve()
    found = detect(root)
    report = InitReport(root=root, mode=mode, detection=found)

    base = root / ".seamspec"
    for d in LEDGER_DIRS:
        (base / d).mkdir(parents=True, exist_ok=True)

    _write_if_missing(root, CONFIG_REL.as_posix(), render_config(mode, found.runners), report)

    # Follow the config actually on disk, so re-running init after editing it stays consistent.
    for runner in load_config(root).runners.values():
        (root / runner.harness_dir).mkdir(parents=True, exist_ok=True)
        for rel in runner.config_files:
            if rel in RUNNER_CONFIG_TEMPLATES:
                _write_if_missing(root, rel, _template(RUNNER_CONFIG_TEMPLATES[rel]), report)

    _merge_gitignore(root, report)
    if claude_md:
        report.add("CLAUDE.md", directive.install(root))
    return report
