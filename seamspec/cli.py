"""`seamspec` command line (SPEC §15)."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Annotated, Any

import typer

from . import __version__
from . import review as review_mod
from .core import journal, lifecycle, requests, tree, trust, verifier
from .core.config import ConfigError, load_config
from .core.context import constraints_for
from .core.models import DeadEnd, Invariant, InvStatus
from .core.root import RootNotFound, find_root
from .core.scope import matches
from .core.store import RecordError, Store
from .installers import ci as ci_installer
from .installers import claude_plugin, scaffold
from .installers.directive import DirectiveError

app = typer.Typer(
    name="seamspec",
    help="Executable specs for AI coding agents. Build first; every seam that works gets a spec.",
    no_args_is_help=True,
    add_completion=False,
)


def _fail(message: str, code: int = 1) -> typer.Exit:
    typer.echo(f"seamspec: {message}", err=True)
    return typer.Exit(code)


def _open() -> tuple[Path, Any, Store]:
    try:
        root = find_root()
        return root, load_config(root), Store(root)
    except (RootNotFound, ConfigError) as exc:
        raise _fail(str(exc)) from None


def _version(value: bool) -> None:
    if value:
        typer.echo(f"seamspec {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Show the version and exit.")
    ] = False,
) -> None:
    pass


CONSENT_SCREEN = """\
SeamSpec will automatically run your LOCKED (human-approved) tests:
  • when the agent tries to finish a task (Stop hook)
  • before every git commit (pre-commit)

These tests import project code that the agent may have changed.
They run with YOUR user permissions. There is no sandbox.
Secrets are stripped from the environment, but files on disk are readable.
"""


PLUGIN_SCREEN = """\
Claude Code plugin: shows the agent the locked rules as it edits, runs them before it
finishes (Stop hook), and adds the SeamSpec MCP tools and /seamspec:lock, /seamspec:dead-end.
SeamSpec will run:"""


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _untrusted_config(root: Path) -> Any:
    """The existing config of a clone this machine hasn't trusted yet, else None."""
    if not (root / ".seamspec/config.toml").is_file():
        return None
    try:
        cfg = load_config(root)
    except ConfigError:
        return None  # init reports it
    return None if trust.state(Store(root), cfg).trusted else cfg


_PLAIN_TOKEN = re.compile(r"[\w@%+=:,./{}\[\]-]+", re.ASCII)


def _shown(token: str) -> str:
    """A config value as it is safe to print: committed config may come from someone else, and
    newlines or terminal escapes in it could repaint a trust screen. Anything not plain is
    printed JSON-quoted, which also keeps argv token boundaries visible."""
    return token if _PLAIN_TOKEN.fullmatch(token) else json.dumps(token)


def _echo_runners(cfg: Any) -> None:
    for name, r in sorted(cfg.runners.items()):
        typer.echo(f"  [{_shown(name)}] {' '.join(_shown(t) for t in r.cmd)}")
        if r.env:
            typer.echo(f"          env: {', '.join(f'{_shown(k)}={_shown(v)}' for k, v in r.env.items())}")
    typer.echo(f"Env passthrough: {', '.join(_shown(k) for k in cfg.execution.env_passthrough) or 'none'}")


def _echo_changed_tests(store: Store, ids: list[str]) -> None:
    for inv_id in ids:
        typer.echo(f"  new/changed since last trust: {inv_id} {_shown(store.get(inv_id).verification.harness_path)}")


@app.command()
def init(
    mode: Annotated[
        scaffold.Mode | None,
        typer.Option(
            help="advisory | enforced | strict (SPEC §7.3). Default: keep enforced/strict as they are; "
            "otherwise offer enforced. Lowering the mode needs a human at a terminal."
        ),
    ] = None,
    path: Annotated[Path, typer.Option(help="Repository root to set up.")] = Path("."),
    claude_md: Annotated[
        bool, typer.Option("--claude-md/--no-claude-md", help="Write the SeamSpec block into CLAUDE.md.")
    ] = True,
    plugin: Annotated[
        bool | None,
        typer.Option(
            "--plugin/--no-plugin",
            help="Install and enable the SeamSpec Claude Code plugin for this repository only. Asks when omitted.",
        ),
    ] = None,
    ci: Annotated[
        bool | None,
        typer.Option(
            "--ci/--no-ci",
            help="Add the CI workflow (enforced mode asks when omitted; strict always adds it; advisory never).",
        ),
    ] = None,
    accept_auto_run: Annotated[
        bool,
        typer.Option(
            "--accept-auto-run",
            help="Answer yes to the auto-run consent screen (for scripted setups). Nothing else implies it.",
        ),
    ] = False,
) -> None:
    """Set up SeamSpec in this repository. Safe to re-run: existing files are kept or merged."""
    root = path.resolve()
    if not root.is_dir():
        raise _fail(f"{root} is not a directory")

    current = scaffold.current_mode(root)
    target = mode or scaffold.default_mode(current)
    lowering = current is not None and scaffold.MODE_RANK[target] < scaffold.MODE_RANK[current]
    if lowering:
        # Lowering the mode switches checks off, so it's a human decision, like approving (ADR-20261007-1b4c).
        try:
            lifecycle.require_interactive()
        except lifecycle.ApprovalError:
            raise _fail(
                f"Lowering the mode ({current} → {target}) turns SeamSpec's checks down, so a human must do it: "
                "run this command yourself in a terminal."
            ) from None
        if _interactive() and not typer.confirm(f"Lower the mode from {current} to {target}?", default=False):
            raise _fail("mode unchanged")

    # Consent is only asked when raising the mode or setting up. Lowering it, or choosing advisory, asks
    # nothing, so this machine's earlier answer is kept, never overwritten with a "no" nobody gave.
    auto_run: bool | None = None
    trust_shown: str | None = None
    if target != "advisory" and not lowering:
        if accept_auto_run:
            auto_run = True
        elif _interactive():
            typer.echo(CONSENT_SCREEN)
            # A fresh clone: its committed runner commands need trust too. One question covers both.
            untrusted = _untrusted_config(root)
            if untrusted is not None:
                store = Store(root)
                locked = trust.locked_harnesses(store)
                typer.echo("This clone's .seamspec/config.toml would run:")
                _echo_runners(untrusted)
                typer.echo(f"Locked tests: {len(locked)} (trust level: {untrusted.execution.trust_level})")
                _echo_changed_tests(store, trust.state(store, untrusted).new_or_changed_tests)
            question = "Allow automatic test runs" + (" with these commands" if untrusted else "")
            auto_run = typer.confirm(f"{question} in this repository?", default=False)
            if auto_run and untrusted is not None:  # bound to exactly what was shown (ADR-20261005-9b8f)
                trust_shown = trust.trust_hash(untrusted, locked)
        else:
            auto_run = None  # nobody was asked: keep this machine's earlier answer, if any
            typer.echo(
                "Not a terminal and no --accept-auto-run: no consent asked. A new setup stays in advisory mode;"
                " an earlier answer on this machine is kept."
            )
    try:
        report = scaffold.init(root, mode=target, claude_md=claude_md, auto_run=auto_run, trust_shown=trust_shown)
    except (DirectiveError, ConfigError) as exc:
        raise _fail(str(exc)) from None

    typer.echo(f"SeamSpec initialised in {root} (mode: {report.mode})")
    for rel, what in report.actions:
        typer.echo(f"  {what:<9} {rel}")
    found = report.detection
    typer.echo(
        "Runners: "
        + (", ".join(found.runners) or "none detected (presets left commented out in .seamspec/config.toml)")
    )
    for name in found.unsupported:
        typer.echo(f"  note: {name} detected; support arrives in v0.2 (SPEC §12A.2)")
    for note in found.notes:
        typer.echo(f"  note: {note}")
    if report.hook is not None:
        if report.hook.status in ("created", "updated", "unchanged", "removed"):
            typer.echo(f"  {report.hook.status:<9} git pre-commit hook ({report.hook.path})")
        else:
            typer.echo(f"  note: {report.hook.message}")
    if not report.consent and report.mode != "advisory":
        typer.echo(f"Automatic test runs are off on this machine (the repository's mode is {report.mode}). "
                   "Re-run `seamspec init` to turn them on.")  # fmt: skip
    elif not report.consent and target != "advisory":
        typer.echo("Automatic test runs are off (advisory mode). Re-run `seamspec init` to turn them on.")
    if not report.trusted and trust_shown is not None:
        typer.echo("The runner settings changed after they were shown (for example --mode strict switched")
        typer.echo("trust_level), so this clone isn't trusted yet: run `seamspec trust` to review them.")
    elif not report.trusted:
        typer.echo("This clone isn't trusted yet: run `seamspec trust` to review its runner commands.")
    if not (root / ".git").exists():
        typer.echo("  note: not a git repository; SeamSpec's checks compare against git HEAD.")
    _init_ci(root, report.mode, ci)
    _init_plugin(root, plugin)


def _init_ci(root: Path, mode: str, wanted: bool | None) -> None:
    """CI by mode (§7.3): never in advisory, offered in enforced, always in strict (+ CODEOWNERS)."""
    if mode == "advisory":
        if wanted:
            typer.echo("CI workflow: not installed (advisory mode never adds one, §7.3).")
        return
    if mode == "enforced" and wanted is False:
        return
    if mode == "strict" and wanted is False:
        typer.echo("CI workflow: strict mode always adds it (§7.3); --no-ci is ignored.")
    if mode == "enforced" and wanted is None:
        if not _interactive():
            typer.echo("CI workflow: not added (no terminal). Run `seamspec init --ci` to add it.")
            return
        question = f"Add a CI workflow ({ci_installer.WORKFLOW_REL}) that runs your approved rules on every PR?"
        if not typer.confirm(question, default=True):
            return
    cfg = load_config(root)
    typer.echo(f"  {ci_installer.install_workflow(root, cfg):<9} {ci_installer.WORKFLOW_REL}")
    if mode == "strict":
        typer.echo(f"  {ci_installer.install_codeowners(root, cfg):<9} {ci_installer.CODEOWNERS_REL}"
                   " (replace @your-team/leads with your reviewers)")  # fmt: skip


def _init_plugin(root: Path, wanted: bool | None) -> None:
    """Offer the Claude Code plugin (SPEC §16.1). Changing Claude Code's settings needs a yes."""
    if wanted is False:
        return
    if wanted is None and not _interactive():
        typer.echo("Claude Code plugin: not checked (no terminal). Run `seamspec init --plugin` to install it.")
        return
    result = claude_plugin.precheck(root)
    if result is None:
        source = claude_plugin.marketplace_source()
        assert source is not None  # precheck() checked it
        if wanted is None:
            typer.echo(PLUGIN_SCREEN)
            for args in claude_plugin.commands(source):
                typer.echo(f"  claude plugin {' '.join(args)}")
            typer.echo(
                f"It would be enabled in {claude_plugin.SETTINGS_LOCAL}: just you, just this repository."
                " Claude Code would also record the install in its config directory (normally"
                " ~/.claude/plugins/); nothing is turned on elsewhere."
            )
            if not typer.confirm("Install the SeamSpec plugin for Claude Code in this repository?", default=True):
                typer.echo("Claude Code plugin: not installed. Run `seamspec init --plugin` any time.")
                return
        result = claude_plugin.enable(root)
    typer.echo(f"Claude Code plugin: {result.status} ({result.message})")
    if result.gitignore in ("created", "updated"):
        typer.echo(f"  {result.gitignore:<9} .gitignore ({claude_plugin.SETTINGS_LOCAL})")
    if result.status == "installed":
        typer.echo("  Start a new Claude Code session (or run /reload-plugins) to load it.")


def _status_data(store: Store, cfg: Any) -> dict[str, Any]:
    invs = store.load_all("inv")
    des = store.load_all("de")
    inv_counts = Counter(i.status.value for i in invs if isinstance(i, Invariant))
    de_counts = Counter(d.status for d in des if isinstance(d, DeadEnd))
    last = store.local / "last_verify.json"
    last_verify = None
    if last.is_file():
        try:
            last_verify = json.loads(last.read_text(encoding="utf-8"))
        except ValueError:
            last_verify = None
    return {
        "mode": cfg.mode,
        "runners": sorted(cfg.runners),
        "invariants": {s.value: inv_counts.get(s.value, 0) for s in InvStatus},
        "dead_ends": {s: de_counts.get(s, 0) for s in ("ACTIVE", "RETIRED")},
        "awaiting_review": inv_counts.get(InvStatus.PROPOSED.value, 0) + len(requests.pending_supersede_ids(store)),
        "supersede_requests": sorted(requests.pending_supersede_ids(store)),
        "last_verify": last_verify,
    }


@app.command()
def status(as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False) -> None:
    """Counts by status, pending reviews and the last verify result."""
    root, cfg, store = _open()
    try:
        data = _status_data(store, cfg)
    except RecordError as exc:
        raise _fail(f"bad record: {exc}") from None
    if as_json:
        typer.echo(json.dumps(data, indent=2))
        return
    inv, de = data["invariants"], data["dead_ends"]
    typer.echo(f"SeamSpec · {root}")
    typer.echo(f"  mode        {data['mode']}")
    typer.echo(f"  runners     {', '.join(data['runners']) or 'none configured'}")
    typer.echo("  invariants  " + "  ".join(f"{k.lower()} {v}" for k, v in inv.items()))
    typer.echo(f"  dead ends   active {de['ACTIVE']}  retired {de['RETIRED']}")
    lv = data["last_verify"]
    typer.echo(f"  last verify {'never' if lv is None else ('passed' if lv.get('passed') else 'FAILED')}")
    if data["awaiting_review"]:
        typer.echo(f"{data['awaiting_review']} awaiting review: run `seamspec review`.")


@app.command()
def context(
    files: Annotated[list[str], typer.Argument(help="Files you are about to change.")],
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Show the invariants and dead ends that apply to FILES (MCP-free fallback for agents)."""
    root, _cfg, store = _open()
    try:
        cs = constraints_for(store, [str((Path.cwd() / f).resolve()) for f in files])
    except RecordError as exc:
        raise _fail(f"bad record: {exc}") from None
    if as_json:
        typer.echo(json.dumps(cs.to_dict(), indent=2))
        return
    shown = ", ".join(cs.files) or "(no files inside this repository)"
    if not (cs.locked or cs.proposed or cs.dead_ends):
        typer.echo(f"SeamSpec: no invariants or dead ends apply to {shown}.")
        return
    typer.echo(f"SeamSpec: {shown} {'is' if len(cs.files) == 1 else 'are'} governed by:")
    typer.echo(cs.render())


# --- lifecycle (SPEC §11, §15) ------------------------------------------------------------------


def _read_json_stdin() -> dict[str, Any]:
    try:
        data = json.loads(sys.stdin.read())
    except ValueError as exc:
        raise _fail(f"stdin is not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise _fail("stdin must be a JSON object")
    return data


def _emit(result: dict[str, Any]) -> None:
    typer.echo(json.dumps(result, indent=2))
    if "error" in result:
        raise typer.Exit(1)


PROPOSE_KEYS = {
    "title", "assertion", "scope_paths", "runner", "harness_code", "origin_text",
    "origin_type", "origin_ref", "scope_tags", "replace_id", "adr",
}  # fmt: skip


@app.command()
def propose(
    from_json: Annotated[str, typer.Option("--json", help="Read the proposal as JSON from stdin ('-').")] = "-",
) -> None:
    """Propose an invariant (agents without MCP). Same fields as the MCP propose_invariant tool (§14.1).
    Nothing runs: afterwards, run `seamspec verify --proposed <id>`."""
    if from_json != "-":
        raise _fail("only `--json -` (stdin) is supported")
    _root_dir, cfg, store = _open()
    data = _read_json_stdin()
    unknown = sorted(set(data) - PROPOSE_KEYS)
    if unknown:
        raise _fail(f"unknown fields: {', '.join(unknown)}")
    missing = sorted({"title", "assertion", "scope_paths", "runner", "harness_code", "origin_text"} - set(data))
    if missing:
        raise _fail(f"missing fields: {', '.join(missing)}")
    adr_draft = data.pop("adr", None)
    try:
        _emit(lifecycle.propose_invariant(store, cfg, adr_draft=adr_draft, **data))
    except (lifecycle.LifecycleError, KeyError, TypeError) as exc:
        _emit({"error": "invalid", "message": str(exc)})


@app.command("dead-end")
def dead_end(
    from_json: Annotated[str, typer.Option("--json", help="Read the dead end as JSON from stdin ('-').")] = "-",
) -> None:
    """Record an approach that was tried and failed (agents without MCP). No approval needed."""
    if from_json != "-":
        raise _fail("only `--json -` (stdin) is supported")
    _root_dir, cfg, store = _open()
    data = _read_json_stdin()
    allowed = {"scope_paths", "approach", "failure_symptom", "related_invariant"}
    if set(data) - allowed or not {"scope_paths", "approach", "failure_symptom"} <= set(data):
        raise _fail(f"expected fields: {', '.join(sorted(allowed))} (related_invariant optional)")
    try:
        _emit(lifecycle.log_dead_end(store, cfg, **data))
    except (lifecycle.LifecycleError, KeyError) as exc:
        _emit({"error": "invalid", "message": str(exc)})


def _human_only() -> None:
    try:
        lifecycle.require_interactive()
    except lifecycle.ApprovalError as exc:
        raise _fail(str(exc)) from None


_show_invariant = review_mod.show_invariant


def _get_invariant(store: Store, inv_id: str) -> Invariant:
    try:
        inv = store.get(inv_id)
    except KeyError:
        raise _fail(f"no such invariant: {inv_id}") from None
    if not isinstance(inv, Invariant):
        raise _fail(f"{inv_id} is not an invariant")
    return inv


@app.command()
def approve(inv_id: Annotated[str, typer.Argument(help="PROPOSED invariant to lock.")]) -> None:
    """Lock a proposed invariant (human only). Shows its full test first, then runs it."""
    _human_only()
    _root_dir, cfg, store = _open()
    inv = _get_invariant(store, inv_id)
    _show_invariant(store, inv)
    confirm_config: dict[str, str] | None = None
    if verifier.check_fingerprints(store.root, cfg):
        typer.echo("Runner config changed since it was last confirmed (approving also confirms it):")
        shown = review_mod.show_config_changes(store, cfg)
        if not typer.confirm("Confirm these runner config changes too?", default=False):
            raise _fail("not approved: runner config changes not confirmed (see `seamspec review`)")
        confirm_config = shown
    if not typer.confirm(f"Run this test and lock {inv_id}?", default=False):
        raise _fail("not approved", code=1)
    try:
        result = lifecycle.approve(store, cfg, inv_id, confirm_config=confirm_config)
    except lifecycle.LifecycleError as exc:
        raise _fail(str(exc)) from None
    typer.echo(f"LOCKED {inv_id} (test: {result.invariant.verification.harness_path})")


@app.command()
def reject(
    inv_id: Annotated[str, typer.Argument(help="PROPOSED invariant to reject.")],
    reason: Annotated[str, typer.Option(help="Why it is rejected.")],
    dead_end: Annotated[bool, typer.Option("--dead-end", help="Also record the approach as a dead end.")] = False,
) -> None:
    """Reject a proposed invariant (human only)."""
    _human_only()
    _root_dir, cfg, store = _open()
    try:
        out = lifecycle.reject(store, cfg, inv_id, reason, as_dead_end=dead_end)
    except (lifecycle.LifecycleError, KeyError) as exc:
        raise _fail(str(exc)) from None
    extra = f"; dead end {out['dead_end']} recorded" if "dead_end" in out else ""
    typer.echo(f"REJECTED {inv_id}{extra}")


@app.command()
def supersede(
    inv_id: Annotated[str, typer.Argument(help="LOCKED invariant to retire or replace.")],
    reason: Annotated[str | None, typer.Option(help="Why the rule changes.")] = None,
    replacement: Annotated[str | None, typer.Option(help="Invariant that replaces it.")] = None,
    request: Annotated[
        bool, typer.Option("--request", help="Agent: only ask for the supersede; a human approves it later.")
    ] = False,
) -> None:
    """Retire a LOCKED invariant (human), or request that (agent, with --request)."""
    _root_dir, cfg, store = _open()
    if request:
        if not reason:
            raise _fail("--request needs --reason")
        try:
            _emit(lifecycle.request_supersede(store, inv_id, reason, replacement))
        except (lifecycle.LifecycleError, KeyError) as exc:
            _emit({"error": "invalid", "message": str(exc)})
        return
    _human_only()
    inv = _get_invariant(store, inv_id)
    _show_invariant(store, inv)
    pending = requests.get(store, inv_id)
    if pending:
        typer.echo(f"  pending request: {pending.reason} (replacement: {pending.replacement_id or 'none'})")
    if not typer.confirm(f"Supersede {inv_id}? Its test stops running.", default=False):
        raise _fail("not superseded", code=1)
    try:
        out = lifecycle.supersede(store, cfg, inv_id, reason, replacement)
    except (lifecycle.LifecycleError, KeyError) as exc:
        raise _fail(str(exc)) from None
    typer.echo(f"SUPERSEDED {inv_id}" + (f" by {out['superseded_by']}" if out["superseded_by"] else ""))


@app.command("retire-dead-end")
def retire_dead_end(
    de_id: Annotated[str, typer.Argument(help="ACTIVE dead end to retire.")],
    reason: Annotated[str, typer.Option(help="Why the approach is worth trying again.")],
) -> None:
    """Retire a dead end (human only), e.g. after a library upgrade fixed the problem."""
    _human_only()
    _root_dir, _cfg, store = _open()
    try:
        lifecycle.retire_dead_end(store, de_id, reason)
    except (lifecycle.LifecycleError, KeyError) as exc:
        raise _fail(str(exc)) from None
    typer.echo(f"RETIRED {de_id}")


@app.command()
def review() -> None:
    """Review everything waiting for you: runner config changes, new dead ends, supersede requests,
    and proposed rules (each with its full test and a red-green check). Human only."""
    _human_only()
    _root_dir, cfg, store = _open()
    try:
        review_mod.run(store, cfg)
    except (RecordError, lifecycle.LifecycleError) as exc:
        raise _fail(str(exc)) from None


# --- trust and verify (SPEC §12.4.6, §16.4) -------------------------------------------------------


@app.command("trust")
def trust_cmd(
    show: Annotated[bool, typer.Option("--show", help="Only print the current trust state.")] = False,
) -> None:
    """Trust this clone for automatic test runs, after reviewing what would run (human only)."""
    _root_dir, cfg, store = _open()
    st = trust.state(store, cfg)
    typer.echo(f"Trust: {'trusted' if st.trusted else 'NOT trusted'}" + (f" ({st.reason})" if st.reason else ""))
    if st.by:
        typer.echo(f"  last trusted by {st.by} at {st.at}")
    if show:
        return
    typer.echo("Runner commands that will run:")
    _echo_runners(cfg)
    locked = trust.locked_harnesses(store)
    typer.echo(f"Locked tests: {len(locked)} (trust level: {cfg.execution.trust_level})")
    _echo_changed_tests(store, st.new_or_changed_tests)
    if st.trusted:
        return
    _human_only()
    if not typer.confirm("Trust this clone to run these automatically?", default=False):
        raise _fail("not trusted")
    trust.grant(store, cfg, lifecycle.approver_identity(store))
    typer.echo("Trusted.")


def _verify_text(report: verifier.VerifyReport, problems: list[str]) -> str:
    lines = list(problems) + list(report.config_failures) + list(report.integrity_failures)
    for r in report.results:
        if r.passed:
            continue
        who = ", ".join(r.failed_ids or r.invariant_ids)
        tag = "INCOMPLETE" if r.incomplete else "FAIL"
        lines.append(f"[{tag}] {who} ({r.runner})\n{r.output}")
    return "\n".join(lines)


@app.command()
def doctor(
    ci: Annotated[
        bool, typer.Option("--ci", help="CI mode: also check the ledger against the base branch; skip local state.")
    ] = False,
    base: Annotated[
        str | None,
        typer.Option(help="Base ref for --ci (default: origin/$GITHUB_BASE_REF on pull requests, else HEAD~1)."),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Check that SeamSpec is healthy here; --ci adds forward-only checks and the retirement summary (§16.5)."""
    from .core import doctor as doctor_mod

    try:
        root = find_root()
    except RootNotFound as exc:
        raise _fail(str(exc)) from None
    report = doctor_mod.run(root, ci=ci, base_ref=base)
    if as_json:
        typer.echo(json.dumps(report.to_dict(), indent=2))
    else:
        typer.echo(f"SeamSpec doctor · {root}" + (" (CI)" if ci else ""))
        for check in report.checks:
            found = [f for f in report.findings if f.check == check]
            if not found:
                typer.echo(f"  ✓ {check}")
            for f in found:
                typer.echo(f"  {'✗' if f.level == 'error' else '!'} {check}: {f.message}")
        errors = sum(f.level == "error" for f in report.findings)
        warnings = len(report.findings) - errors
        typer.echo(f"{errors} error(s), {warnings} warning(s)")
        if report.summary:
            typer.echo("\n" + report.summary)
    if report.summary:
        doctor_mod.write_step_summary(report.summary)
    if not report.ok:
        raise typer.Exit(1)


@app.command()
def verify(
    all_: Annotated[bool, typer.Option("--all", help="Run every LOCKED invariant (the default).")] = False,
    changed: Annotated[
        bool, typer.Option("--changed", help="Only invariants whose scope matches changed files.")
    ] = False,
    proposed: Annotated[
        list[str] | None, typer.Option("--proposed", help="Run a PROPOSED invariant's test (repeatable).")
    ] = None,
    gate: Annotated[
        bool, typer.Option("--gate", help="Pre-commit mode: also check the journal; exit 1 on failure.")
    ] = False,
    ci: Annotated[
        bool, typer.Option("--ci", help="CI mode: skip local trust/consent; CI policy is the consent.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Run invariant tests. Exits 1 if anything fails (SPEC §12.2, §16.4)."""
    root, cfg, store = _open()
    if sum(map(bool, (all_, changed, proposed))) > 1:
        raise _fail("use only one of --all, --changed, --proposed")

    if gate and not ci and cfg.mode == "advisory":  # advisory never runs tests automatically (§7.3)
        typer.echo("SeamSpec is in advisory mode: the pre-commit check runs nothing.")
        return
    if not ci:
        st = trust.state(store, cfg)
        if not st.trusted:
            if gate or not _interactive():
                raise _fail(f"This clone is not trusted ({st.reason}). Run `seamspec trust`.")
            typer.echo(f"This clone is not trusted ({st.reason}).")
            trust_cmd(show=False)
        if gate and not trust.consent_given(store):
            raise _fail("automatic test runs aren't allowed on this machine. Re-run `seamspec init`.")

    problems = journal.unjournaled_changes(store) if gate else []
    try:
        if proposed:
            invs = []
            for inv_id in proposed:
                inv = store.get(inv_id)
                if not isinstance(inv, Invariant) or inv.status != InvStatus.PROPOSED:
                    raise _fail(f"{inv_id} is not a PROPOSED invariant")
                invs.append(inv)
            report = verifier.VerifyReport(passed=True)
            for inv in invs:
                with lifecycle.harness_in_place(store, cfg, inv) as staged:
                    one = verifier.run(root, cfg, [staged])
                report.results += one.results
                report.config_failures = one.config_failures
            report.passed = not report.config_failures and all(r.passed for r in report.results)
        else:
            locked = [i for i in store.load_all("inv") if isinstance(i, Invariant) and i.status == InvStatus.LOCKED]
            if changed:
                files = tree.changed_files(root)
                if files is not None:
                    locked = [i for i in locked if any(matches(i.scope.paths, f) for f in files)]
            report = verifier.run(root, cfg, locked)
            verifier.save_last(root, report)
    except (RecordError, KeyError, lifecycle.LifecycleError) as exc:
        raise _fail(str(exc)) from None

    ok = report.passed and not problems
    pending = len([i for i in store.load_all("inv") if i.status == InvStatus.PROPOSED])
    if as_json:
        typer.echo(json.dumps({**report.to_dict(), "journal_problems": problems, "passed": ok}, indent=2))
    else:
        ran = sum(len(r.invariant_ids) for r in report.results)
        if ok:
            typer.echo(f"SeamSpec: {ran} invariant(s) passed.")
        else:
            typer.echo("SeamSpec: verification failed.\n" + _verify_text(report, problems), err=gate)
            if not proposed:
                typer.echo(
                    "Fix the regression, or if the change is intentional, supersede the rule "
                    "(`seamspec supersede <id> --reason ...`).",
                    err=gate,
                )
        if gate and pending:
            typer.echo(f"SeamSpec: {pending} item(s) awaiting review: run `seamspec review`.", err=True)
    if not ok:
        raise typer.Exit(1)


@app.command("mcp")
def mcp_cmd() -> None:
    """Run the SeamSpec MCP server on stdio (started by the Claude Code plugin or another MCP client)."""
    from .mcp_server import run

    run()


@app.command(hidden=True)
def hook(
    host: Annotated[str, typer.Argument(help="Host adapter: claude")],
    event: Annotated[str, typer.Argument(help="Hook event: pre-tool-use | stop | session-start")],
) -> None:
    """Internal: host hook entry point. Reads the hook payload on stdin; always exits 0."""
    if host != "claude":
        typer.echo(f"seamspec hook: unknown host {host!r} (v0.1 supports claude)", err=True)
        return
    from .adapters import claude

    if event not in claude.HANDLERS:
        typer.echo(f"seamspec hook: unknown event {event!r}", err=True)
        return
    out = claude.main(event)
    if out:
        typer.echo(out)


def main() -> None:
    app()
