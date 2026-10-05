"""`seamspec` command line (SPEC §15)."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Annotated, Any

import typer

from . import __version__
from .core import lifecycle, requests
from .core.config import ConfigError, load_config
from .core.context import constraints_for
from .core.models import DeadEnd, Invariant, InvStatus
from .core.root import RootNotFound, find_root
from .core.store import RecordError, Store
from .installers import scaffold
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


@app.command()
def init(
    mode: Annotated[scaffold.Mode, typer.Option(help="advisory | enforced | strict (SPEC §7.3)")] = "enforced",
    path: Annotated[Path, typer.Option(help="Repository root to set up.")] = Path("."),
    claude_md: Annotated[
        bool, typer.Option("--claude-md/--no-claude-md", help="Write the SeamSpec block into CLAUDE.md.")
    ] = True,
) -> None:
    """Set up SeamSpec in this repository. Safe to re-run: existing files are kept or merged."""
    root = path.resolve()
    if not root.is_dir():
        raise _fail(f"{root} is not a directory")
    try:
        report = scaffold.init(root, mode=mode, claude_md=claude_md)
    except (DirectiveError, ConfigError) as exc:
        raise _fail(str(exc)) from None

    typer.echo(f"SeamSpec initialised in {root} (mode: {mode})")
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
    if not (root / ".git").exists():
        typer.echo("  note: not a git repository; SeamSpec's checks compare against git HEAD.")
    typer.echo("Hooks, pre-commit and CI are installed by later versions of `init` (v0.1 is in progress).")


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


def _show_invariant(store: Store, inv: Invariant) -> None:
    typer.echo(f"{inv.id} [{inv.status.value}] {inv.title}")
    typer.echo(f"  rule:   {inv.assertion}")
    typer.echo(f"  scope:  {', '.join(inv.scope.paths)}")
    typer.echo(f"  origin: {inv.origin.type}: {inv.origin.text[:300]}")
    typer.echo(f"  test:   {inv.verification.harness_path} (runner: {inv.verification.runner})")
    harness = store.root / inv.verification.harness_path
    if harness.is_file():
        typer.echo("  " + "-" * 60)
        for line in harness.read_text(encoding="utf-8").splitlines():
            typer.echo(f"  | {line}")
        typer.echo("  " + "-" * 60)


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
    if not typer.confirm(f"Run this test and lock {inv_id}?", default=False):
        raise _fail("not approved", code=1)
    try:
        result = lifecycle.approve(store, cfg, inv_id)
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


def main() -> None:
    app()
