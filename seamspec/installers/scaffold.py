"""`seamspec init` scaffolding (SPEC §9.1, §12.3, §12A.7, §15).

Merges into existing files and never clobbers: an existing config.toml or runner config is kept
as is, `.gitignore` only gains missing lines, and CLAUDE.md only changes between the markers.
Hooks, the Claude Code plugin, pre-commit, CI and the auto-run consent screen are installed by
later steps (roadmap weeks 2-4, SPEC §22).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Literal

from ..core import trust
from ..core.config import load_config, parse_config
from ..core.lifecycle import approver_identity
from ..core.root import CONFIG_REL
from ..core.runners import V01_PRESETS, Detection, detect, preset_toml
from ..core.store import Store, atomic_write
from ..core.verifier import FINGERPRINTS_REL, confirm_fingerprints, current_fingerprints
from . import directive, git_hooks

Mode = Literal["advisory", "enforced", "strict"]
MODE_RANK = {"advisory": 0, "enforced": 1, "strict": 2}  # lowering the mode is a human decision (CLI)

LEDGER_DIRS = ("invariants", "dead_ends", "adrs", "proposed", "retired", ".local")
GITIGNORE_LINES = (
    ".seamspec/.local/",
    ".seamspec/**/__pycache__/",  # bytecode from SeamSpec's own pytest runs never belongs in the ledger
)
LOCAL_GITIGNORE = ".seamspec/.local/.gitignore"
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
    consent: bool = False
    trusted: bool = False
    hook: git_hooks.HookResult | None = None

    def add(self, path: str, what: str) -> None:
        self.actions.append((path, what))


def _template(name: str) -> str:
    return files("seamspec.templates").joinpath(name).read_text("utf-8")


STRICT_HOOKS = "fail_closed = true             # strict mode default\n"
NON_STRICT_HOOKS = "fail_closed = false            # strict mode defaults to true\n"
STRICT_TRUST = 'trust_level = "harness"        # strict mode default\n'
NON_STRICT_TRUST = 'trust_level = "runners"        # runners | harness\n'
STRICT_REVIEW = "chat_approvals = false         # strict mode default: approve in the terminal only\n"
NON_STRICT_REVIEW = "chat_approvals = true          # approve in a chat dialog too; strict mode defaults to false\n"


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
        .replace("{{hooks_extra}}", STRICT_HOOKS if strict else NON_STRICT_HOOKS)
        .replace("{{execution_extra}}", STRICT_TRUST if strict else NON_STRICT_TRUST)
        .replace("{{review_extra}}", STRICT_REVIEW if strict else NON_STRICT_REVIEW)
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


def merge_gitignore(
    root: Path, lines: tuple[str, ...] = GITIGNORE_LINES, header: str = "SeamSpec: machine-local state and caches"
) -> str:
    """Add the missing `lines` to `.gitignore`: created | updated | unchanged."""
    path = root / ".gitignore"
    old = path.read_text(encoding="utf-8") if path.is_file() else ""
    present = {ln.strip() for ln in old.splitlines()}
    missing = [ln for ln in lines if ln not in present]
    if not missing:
        return "unchanged"
    sep = "" if not old or old.endswith("\n") else "\n"
    block = f"\n# {header}\n" + "\n".join(missing) + "\n"
    atomic_write(path, old + sep + (block if old else block.lstrip("\n")))
    return "updated" if old else "created"


def _record_initial_fingerprints(root: Path, report: InitReport) -> None:
    """The human running `init` confirms the runner config it just wrote (§12.2). Only when no
    fingerprints exist yet: later changes must be confirmed in `seamspec review`."""
    path = root / FINGERPRINTS_REL
    if path.exists():
        report.add(FINGERPRINTS_REL.as_posix(), "kept")
        return
    confirm_fingerprints(root, current_fingerprints(root, load_config(root)))
    report.add(FINGERPRINTS_REL.as_posix(), "created")


def _set_mode(root: Path, mode: Mode) -> None:
    """Rewrite only the top-level `mode = ...` line, keeping comments and everything else."""
    path = root / CONFIG_REL
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith("["):
            break  # top-level keys come before the first table
        if re.match(r"\s*mode\s*=", line):
            comment = line.split("#", 1)[1] if "#" in line else " advisory | enforced | strict\n"
            lines[i] = f'mode = "{mode}"              #{comment}'
            break
    else:
        lines.insert(1 if lines and lines[0].startswith("#") else 0, f'mode = "{mode}"\n')
    text = "".join(lines)
    if mode == "strict":  # init's own non-strict defaults would loosen strict mode; edited values stay
        text = text.replace(NON_STRICT_HOOKS, STRICT_HOOKS).replace(NON_STRICT_TRUST, STRICT_TRUST)
        text = text.replace(NON_STRICT_REVIEW, STRICT_REVIEW)
    else:  # leaving strict: undo only the lines init itself wrote; values a human edited stay
        text = text.replace(STRICT_HOOKS, NON_STRICT_HOOKS).replace(STRICT_TRUST, NON_STRICT_TRUST)
        text = text.replace(STRICT_REVIEW, NON_STRICT_REVIEW)
    parse_config(text, str(path))
    atomic_write(path, text)


def current_mode(root: Path) -> Mode | None:
    """The mode in an existing, loadable config.toml, else None."""
    if not (root / CONFIG_REL).is_file():
        return None
    try:
        return load_config(root).mode
    except Exception:  # noqa: BLE001 - a broken config is reported by init itself
        return None


def default_mode(current: Mode | None) -> Mode:
    """No --mode given: keep enforced or strict as they are (never lowered silently); a new setup,
    or an advisory one, is offered enforced, so re-running init with consent turns runs on."""
    return current if current in ("enforced", "strict") else "enforced"


def init(
    root: Path,
    mode: Mode | None = None,
    claude_md: bool = True,
    auto_run: bool | None = False,
    actor: str | None = None,
    trust_shown: str | None = None,
) -> InitReport:
    """Set up SeamSpec in `root`.

    `auto_run` is the human's answer to the consent screen (§12.4.5); the CLI asks, this function
    never does. `None` means nobody was asked (no terminal, no flag): an answer this machine
    recorded earlier is kept, never overwritten with a "no" nobody gave. Without consent,
    `enforced` and `strict` fall back to `advisory`, and no pre-commit hook is installed.

    Whoever creates the config with `init` also trusts this clone for it (§12.4.6). On a clone,
    `trust_shown` is the trust hash of the runner settings the human said yes to on the combined
    consent-and-trust screen; trust is granted only if what is on disk now still hashes the same
    (a `--mode strict` switch or an edit meanwhile changes it).
    """
    root = root.resolve()
    current = current_mode(root)
    mode = mode or default_mode(current)
    asked = auto_run is not None
    if auto_run is None:
        auto_run = trust.consent_given(Store(root)) if (root / CONFIG_REL).exists() else False
    found = detect(root)
    effective: Mode = mode if auto_run or mode == "advisory" else "advisory"
    report = InitReport(root=root, mode=effective, detection=found)

    base = root / ".seamspec"
    for d in LEDGER_DIRS:
        (base / d).mkdir(parents=True, exist_ok=True)
    # Machine-local state stays out of git on every branch, even one whose .gitignore predates SeamSpec.
    _write_if_missing(root, LOCAL_GITIGNORE, "# SeamSpec machine-local state: never commit.\n*\n", report)

    config_rel = CONFIG_REL.as_posix()
    created_config = not (root / CONFIG_REL).exists()
    _write_if_missing(root, config_rel, render_config(effective, found.runners), report)

    # Switching modes on an existing config (§7.3, ADR-20261007-1b4c). Raising it needs automatic
    # runs allowed on this machine; lowering it is checked as a human decision by the CLI.
    if not created_config and current is not None and mode != current:
        if MODE_RANK[mode] < MODE_RANK[current] or auto_run:  # lowering never needs consent
            _set_mode(root, mode)
            report.add(config_rel, f"updated (mode: {current} → {mode})")
        else:
            report.add(config_rel, f"kept (mode: {current}; {mode} needs automatic runs allowed here)")

    # Follow the config actually on disk, so re-running init after editing it stays consistent.
    cfg = load_config(root)
    report.mode = cfg.mode
    for runner in cfg.runners.values():
        (root / runner.harness_dir).mkdir(parents=True, exist_ok=True)
        for rel in runner.config_files:
            if rel in RUNNER_CONFIG_TEMPLATES:
                _write_if_missing(root, rel, _template(RUNNER_CONFIG_TEMPLATES[rel]), report)

    _record_initial_fingerprints(root, report)
    report.add(".gitignore", merge_gitignore(root))
    if claude_md:
        report.add("CLAUDE.md", directive.install(root))

    store = Store(root)
    who = actor or approver_identity(store)
    if asked:
        trust.record_consent(store, auto_run, who)
    report.consent = auto_run
    shown_still_current = trust_shown is not None and trust_shown == trust.trust_hash(
        cfg, trust.locked_harnesses(store)
    )
    if created_config or (auto_run and shown_still_current):
        trust.grant(store, cfg, who)  # they just wrote, or were just shown, these runner settings
    report.trusted = trust.state(store, cfg).trusted
    if auto_run and cfg.mode != "advisory":
        report.hook = git_hooks.install_pre_commit(root)
    elif cfg.mode == "advisory":  # advisory never runs tests automatically: remove SeamSpec's own hook
        removed = git_hooks.uninstall_pre_commit(root)
        if removed.status == "removed":
            report.hook = removed
    return report
