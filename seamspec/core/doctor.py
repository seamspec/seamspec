"""`seamspec doctor`: is SeamSpec healthy here? (SPEC §15, §16.5)

Local checks: config, record schemas, integrity of LOCKED tests, runner config fingerprints,
approval provenance, the approval journal, the CLAUDE.md block, the git pre-commit hook, scopes
that match no files, and hosts allowlisting SeamSpec commands (§12.4.3 rule 6).

`--ci` drops the machine-local checks (journal, hook) and compares the ledger with the base
branch: LOCKED rules may only move forward (to SUPERSEDED), never be edited, deleted or moved
back, and their tests may not change. It also builds the retirement summary, which never fails
and lists every status change, runner config change and new dead end for the human reviewer.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import journal
from .config import ConfigError, load_config
from .schemas import validation_errors
from .scope import matches
from .verifier import FINGERPRINTS_REL, check_fingerprints, check_integrity

LEDGER = {"invariants": "invariant", "dead_ends": "dead_end"}
# Fields of a LOCKED record that only a supersede may change (forward-only, §16.5).
FROZEN = ("title", "assertion", "scope", "verification", "approved_at", "approved_by")
CRITICAL_MANY = 10  # more critical rules than this gets a warning


@dataclass
class Finding:
    level: str  # error | warning
    check: str
    message: str


@dataclass
class DoctorReport:
    findings: list[Finding] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)  # checks that ran
    summary: str | None = None  # --ci retirement summary (markdown)

    @property
    def ok(self) -> bool:
        return not any(f.level == "error" for f in self.findings)

    def add(self, level: str, check: str, message: str) -> None:
        self.findings.append(Finding(level, check, message))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": self.checks,
            "findings": [vars(f) for f in self.findings],
            "summary": self.summary,
        }


def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def _records_on_disk(root: Path, report: DoctorReport) -> dict[str, dict[str, Any]]:
    """Every ledger record that parses and passes its schema, by id. Problems are reported."""
    out: dict[str, dict[str, Any]] = {}
    for folder, schema in LEDGER.items():
        for path in sorted((root / ".seamspec" / folder).glob("*.json")):
            rel = path.relative_to(root).as_posix()
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                report.add("error", "schema", f"{rel}: not valid JSON ({exc})")
                continue
            errors = validation_errors(schema, data)
            if errors:
                report.add("error", "schema", f"{rel}: {errors[0]}")
                continue
            if data.get("id") != path.stem:
                report.add("error", "schema", f"{rel}: id {data.get('id')!r} doesn't match the file name")
                continue
            out[data["id"]] = data
    return out


def _records_at(root: Path, ref: str) -> dict[str, dict[str, Any]] | None:
    """Ledger records as committed at `ref`; None if the ref can't be read."""
    prefix = _git(root, "rev-parse", "--show-prefix")
    if prefix is None or _git(root, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}") is None:
        return None
    out: dict[str, dict[str, Any]] = {}
    for folder in LEDGER:
        listing = _git(root, "ls-tree", "-r", "--name-only", "--full-tree", ref, "--",
                       f"{prefix.strip()}.seamspec/{folder}/")  # fmt: skip
        for name in (listing or "").splitlines():
            if not name.endswith(".json"):
                continue
            shown = _git(root, "show", f"{ref}:{name}")
            try:
                data = json.loads(shown or "")
            except ValueError:
                continue
            if isinstance(data, dict) and isinstance(data.get("id"), str):
                out[data["id"]] = data
    return out


def _file_at(root: Path, ref: str, rel: str) -> str | None:
    prefix = (_git(root, "rev-parse", "--show-prefix") or "").strip()
    return _git(root, "show", f"{ref}:{prefix}{rel}")


def default_base() -> str:
    """The pull request's base branch on GitHub Actions, else the previous commit."""
    base = os.environ.get("GITHUB_BASE_REF")
    return f"origin/{base}" if base else "HEAD~1"


# --- checks ----------------------------------------------------------------------------------------


def _local_checks(root: Path, cfg: Any, records: dict[str, dict[str, Any]], report: DoctorReport) -> None:
    from ..installers import directive, git_hooks
    from .store import RecordError, Store

    report.checks += ["journal", "directive", "pre-commit hook", "allowlist"]
    try:
        for problem in journal.unjournaled_changes(Store(root)):
            report.add("error", "journal", problem)
    except RecordError:
        report.add("warning", "journal", "skipped: fix the broken record(s) above first")
    if (root / "CLAUDE.md").is_file() and directive.drift(root):
        foreign = len(directive.foreign_in(root))
        if foreign:  # init keeps them (ADR-20261011-b1c8): say so, or the owner hesitates to rerun it
            message = (
                f"{foreign} line{'s' if foreign != 1 else ''} inside the SeamSpec block in CLAUDE.md"
                f" {'were' if foreign != 1 else 'was'} not written by SeamSpec: rerun `seamspec init`,"
                " which keeps them (moved above the block) and updates the block"
            )
        else:
            message = "the SeamSpec block in CLAUDE.md is missing or outdated: rerun `seamspec init`"
        report.add("warning", "directive", message)
    agents = root / directive.AGENTS_FILE  # Cursor, VS Code, Antigravity (ADR-20261013-e8f3)
    if (
        agents.is_file()
        and directive.BEGIN_PREFIX in agents.read_text(encoding="utf-8")
        and directive.drift(root, directive.AGENTS_FILE)
    ):
        report.add(
            "warning", "directive", "the SeamSpec block in AGENTS.md is outdated: rerun `seamspec init --hosts …`"
        )
    hooks = _git(root, "rev-parse", "--git-path", "hooks")
    hook = (root / hooks.strip() / "pre-commit") if hooks else None
    text = hook.read_text(encoding="utf-8", errors="replace") if hook and hook.is_file() else ""
    if cfg.mode != "advisory" and hooks is not None and git_hooks.GATE not in text:
        report.add("warning", "pre-commit hook",
                   f"no git pre-commit hook runs `{git_hooks.GATE}` here: rerun `seamspec init`")  # fmt: skip
    if cfg.mode == "advisory" and git_hooks.MARKER in text:
        report.add("warning", "pre-commit hook", "advisory mode, but SeamSpec's pre-commit hook is still installed "
                   "(it runs nothing in advisory mode): rerun `seamspec init` to remove it")  # fmt: skip
    for name in ("settings.json", "settings.local.json"):
        path = root / ".claude" / name
        try:
            allow = json.loads(path.read_text(encoding="utf-8")).get("permissions", {}).get("allow", [])
        except (OSError, ValueError, AttributeError):
            continue
        for rule in allow if isinstance(allow, list) else []:
            if isinstance(rule, str) and rule.replace(" ", "").startswith(("Bash(seamspec", "Bash(*")):
                report.add("warning", "allowlist", f".claude/{name} allows `{rule}`: proposed tests then run "
                           "without asking you (§12.4.3). That's your choice; just know it.")  # fmt: skip


def _ledger_checks(root: Path, cfg: Any, records: dict[str, dict[str, Any]], report: DoctorReport) -> None:
    from .store import Store

    report.checks += ["integrity", "runner config", "approval provenance", "scope", "mode"]
    if cfg.mode == "strict":  # strict always has CI and CODEOWNERS (§7.3)
        from ..installers import ci as ci_installer

        if not (root / ci_installer.WORKFLOW_REL).is_file():
            report.add("warning", "mode", f"strict mode without {ci_installer.WORKFLOW_REL}: rerun `seamspec init`")
        owners = _read(root / ci_installer.CODEOWNERS_REL) or ""
        if ci_installer.OWNERS_BEGIN not in owners:
            report.add("warning", "mode", f"strict mode without the SeamSpec block in {ci_installer.CODEOWNERS_REL}")
        elif "@your-team/leads" in owners:
            report.add("warning", "mode",
                       f"replace @your-team/leads in {ci_installer.CODEOWNERS_REL} with real reviewers")  # fmt: skip
    store = Store(root)
    tracked = (_git(root, "ls-files") or "").splitlines()
    for inv_id, data in sorted(records.items()):
        if not inv_id.startswith("inv_"):
            continue
        if data.get("status") == "LOCKED":
            if not data.get("approved_at") or not data.get("approved_by"):
                report.add("error", "approval provenance", f"{inv_id} is LOCKED without approved_at/approved_by")
            try:
                problem = check_integrity(root, store.get(inv_id))
            except Exception as exc:  # noqa: BLE001 - schema passed but the model refused it: report, don't crash
                problem = f"{inv_id}: can't be loaded ({exc})"
            if problem:
                report.add("error", "integrity", problem)
        if data.get("status") in ("LOCKED", "PROPOSED") and tracked:
            scope = data.get("scope", {}).get("paths", [])
            if scope and not any(matches(scope, f) for f in tracked):
                report.add("warning", "scope", f"{inv_id}: scope {scope} matches no tracked file (renamed or moved?)")
    for problem in check_fingerprints(root, cfg):
        report.add("error", "runner config", problem)
    critical = sum(
        1 for k, d in records.items() if k.startswith("inv_") and d.get("status") == "LOCKED" and d.get("critical")
    )
    if critical > CRITICAL_MANY:  # ADR-20261013-c1a9: a mark that covers everything means nothing
        report.add("warning", "critical",
                   f"{critical} locked rules are marked critical: the mark is meant for a few rules that must never be"
                   " missed (`seamspec critical <id> --off` clears one)")  # fmt: skip


def _forward_only(root: Path, base_ref: str, now: dict[str, dict[str, Any]], report: DoctorReport) -> dict | None:
    report.checks += ["forward-only", "harness protection"]
    base = _records_at(root, base_ref)
    if base is None:
        report.add("error", "forward-only", f"can't read {base_ref}: in CI, check out with `fetch-depth: 0`")
        return None
    for inv_id, before in sorted(base.items()):
        if not inv_id.startswith("inv_") or before.get("status") != "LOCKED":
            continue
        after = now.get(inv_id)
        if after is None:
            report.add("error", "forward-only", f"{inv_id} was LOCKED on {base_ref} and its record was deleted")
            continue
        status = after.get("status")
        if status == "SUPERSEDED":
            continue
        if status != "LOCKED":
            report.add("error", "forward-only", f"{inv_id} moved back from LOCKED to {status}")
            continue
        if before.get("critical") and not after.get("critical"):  # allowed, but a reviewer should see it
            report.add("warning", "critical", f"{inv_id} is no longer marked critical")
        changed = [f for f in FROZEN if before.get(f) != after.get(f)]
        if changed:
            report.add("error", "forward-only",
                       f"{inv_id} is LOCKED but its {', '.join(changed)} changed without a supersede")  # fmt: skip
        rel = before.get("verification", {}).get("harness_path")
        if rel and _file_at(root, base_ref, rel) != _read(root / rel):
            report.add("error", "harness protection", f"{inv_id}: its test {rel} changed without a supersede")
    return base


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _mode_at(root: Path, ref: str) -> str | None:
    import tomllib

    text = _file_at(root, ref, ".seamspec/config.toml")
    try:
        return str(tomllib.loads(text).get("mode", "enforced")) if text is not None else None
    except tomllib.TOMLDecodeError:
        return None


def retirement_summary(root: Path, base_ref: str, base: dict, now: dict, mode: str | None = None) -> str:
    """Never fails: everything a reviewer must see, even when each change is valid (§16.5)."""
    lines = [f"## SeamSpec: ledger changes against `{base_ref}`", ""]
    base_mode = _mode_at(root, base_ref)
    if mode and base_mode and base_mode != mode:
        lines += [f"**Mode changed: {base_mode} → {mode}**", ""]
    changes = []
    for rec_id in sorted(set(base) | set(now)):
        before = base.get(rec_id, {}).get("status", "(none)")
        after = now.get(rec_id, {}).get("status", "(deleted)")
        if before != after:
            title = (now.get(rec_id) or base.get(rec_id) or {}).get("title") or (
                (now.get(rec_id) or base.get(rec_id) or {}).get("approach", "")[:60]
            )
            changes.append(f"| `{rec_id}` | {title} | {before} → {after} |")
    lines += ["**Status changes**", ""]
    lines += ["| Record | What | Change |", "|---|---|---|", *changes] if changes else ["None."]
    old_prints = json.loads(_file_at(root, base_ref, FINGERPRINTS_REL.as_posix()) or "{}")
    new_prints = json.loads(_read(root / FINGERPRINTS_REL) or "{}")
    changed_cfg = sorted(k for k in set(old_prints) | set(new_prints) if old_prints.get(k) != new_prints.get(k))
    lines += ["", "**Runner config changes** (`.seamspec/fingerprints.json`)", ""]
    lines += [f"- `{k}`" for k in changed_cfg] or ["None."]
    return "\n".join(lines) + "\n"


def run(root: Path, ci: bool = False, base_ref: str | None = None) -> DoctorReport:
    report = DoctorReport()
    report.checks.append("config")
    try:
        cfg = load_config(root)
    except ConfigError as exc:
        report.add("error", "config", str(exc))
        return report
    report.checks.append("schema")
    records = _records_on_disk(root, report)
    _ledger_checks(root, cfg, records, report)
    if ci:
        ref = base_ref or default_base()
        base = _forward_only(root, ref, records, report)
        if base is not None:
            report.summary = retirement_summary(root, ref, base, records, cfg.mode)
    else:
        _local_checks(root, cfg, records, report)
    return report


def write_step_summary(summary: str) -> bool:
    """Append to $GITHUB_STEP_SUMMARY when running on GitHub Actions."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return False
    with open(path, "a", encoding="utf-8") as f:
        f.write(summary)
    return True
