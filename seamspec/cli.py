"""`seamspec` command line (SPEC §15). Week 1: init, status, context."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Annotated, Any

import typer

from . import __version__
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
        "awaiting_review": inv_counts.get(InvStatus.PROPOSED.value, 0),
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


def main() -> None:
    app()
