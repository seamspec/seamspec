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
from .core import braindump, catches, failtext, journal, lifecycle, requests, snapshot, specdoc, tree, trust, verifier
from .core.config import ConfigError, load_config
from .core.context import constraints_for
from .core.models import DeadEnd, Invariant, InvStatus
from .core.root import RootNotFound, find_root
from .core.scope import matches
from .core.store import RecordError, Store, atomic_write
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
Claude Code plugin (for Claude Code only; Cursor, VS Code and Antigravity don't use it):
shows the agent the locked rules as it edits, runs them before it finishes (Stop hook), and
adds the SeamSpec MCP tools and /seamspec:lock, /seamspec:dead-end.
SeamSpec will run:"""

PLUGIN_TEAM_QUESTION = (
    "Turn it on for everyone who works in this repository? It goes into .claude/settings.json, which you"
    " commit; each teammate's Claude Code offers it once they trust the folder. (No: just you.)"
)


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _consented(root: Path) -> bool:
    """This machine already said yes to automatic test runs in this repository."""
    if not (root / ".seamspec/config.toml").is_file():
        return False
    try:
        return trust.consent_given(Store(root))
    except OSError:
        return False


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
            help="Install and enable the SeamSpec Claude Code plugin for this repository. Asks when omitted.",
        ),
    ] = None,
    plugin_scope: Annotated[
        str | None,
        typer.Option(
            "--plugin-scope",
            help="local: just you (.claude/settings.local.json). project: everyone in this repository "
            "(.claude/settings.json, which you commit; released versions only). Asks when omitted; "
            "local without a terminal.",
        ),
    ] = None,
    ci: Annotated[
        bool | None,
        typer.Option(
            "--ci/--no-ci",
            help="Add the CI workflow (enforced mode asks when omitted; strict always adds it; advisory never).",
        ),
    ] = None,
    hosts: Annotated[
        str | None,
        typer.Option(
            "--hosts",
            help="Also set SeamSpec up for these tools: cursor,vscode,antigravity (or none). When omitted, "
            "asks about the ones whose folder exists here.",
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
    if plugin_scope is not None and plugin_scope not in claude_plugin.SCOPES:
        raise typer.BadParameter(f"use {' or '.join(claude_plugin.SCOPES)}", param_hint="--plugin-scope")
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
        elif _interactive() and _consented(root) and _untrusted_config(root) is None:
            # A rerun (e.g. to add an editor) keeps the yes; asking again with "No" as the default
            # could switch the checks off with one Enter (hands-on test, ADR-20261017-7b0e).
            typer.echo(
                "Automatic test runs: already allowed on this machine (`seamspec init --mode advisory` stops them)."
            )
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
    if report.kept_lines:  # never drop someone's own instruction silently (ADR-20261011-b1c8)
        n = len(report.kept_lines)
        typer.echo(
            f"  CLAUDE.md: {n} line{'s' if n != 1 else ''} inside SeamSpec's block {'were' if n != 1 else 'was'}"
            " not SeamSpec's. Kept, and moved above the block:"
        )
        for line in report.kept_lines:
            typer.echo(f"    | {review_mod.cut(line, 160)}")
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
    _init_plugin(root, plugin, plugin_scope)
    _init_hosts(root, hosts)


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
    released = ci_installer.released()
    if mode == "enforced" and wanted is None:
        if not released:
            # Not offered: it couldn't install SeamSpec in most CI setups yet (ADR-20261011-a9f3).
            typer.echo(
                "CI workflow: not offered yet. This SeamSpec isn't a released version, so the workflow would install "
                "it from its repository, which your CI may not be able to read. To add it anyway: `seamspec init --ci`."
            )
            return
        if not _interactive():
            typer.echo("CI workflow: not added (no terminal). Run `seamspec init --ci` to add it.")
            return
        question = f"Add a CI workflow ({ci_installer.WORKFLOW_REL}) that runs your approved rules on every PR?"
        if not typer.confirm(question, default=True):
            return
    cfg = load_config(root)
    outcome = ci_installer.install_workflow(root, cfg)
    typer.echo(f"  {outcome:<9} {ci_installer.WORKFLOW_REL}")
    if outcome == "created" and not released:
        typer.echo(
            f"            It installs SeamSpec from {ci_installer.REPOSITORY} (unreleased build): your CI must be "
            "able to read that repository. After the release, change that line to a version."
        )
    if mode == "strict":
        outcome = ci_installer.install_codeowners(root, cfg)
        placeholder = ci_installer.placeholder_left((root / ci_installer.CODEOWNERS_REL).read_text(encoding="utf-8"))
        hint = f" (replace {ci_installer.PLACEHOLDER_OWNER} with your reviewers)" if placeholder else ""
        typer.echo(f"  {outcome:<9} {ci_installer.CODEOWNERS_REL}{hint}")


def _init_hosts(root: Path, wanted: str | None) -> None:
    """Cursor, VS Code and Antigravity (ADR-20261013-e8f3): project files only, merged, asked first."""
    from .installers import hosts as host_installer

    if wanted is not None and wanted.strip().lower() == "none":
        return
    if wanted is not None:
        chosen = [h.strip().lower() for h in wanted.split(",") if h.strip()]
        unknown = [h for h in chosen if h not in host_installer.HOSTS]
        if unknown:
            raise _fail(f"unknown tool(s): {', '.join(unknown)}; choose from {', '.join(host_installer.HOSTS)}")
    else:
        found = host_installer.detect(root)
        if not found:
            return
        if not _interactive():
            names = ", ".join(host_installer.NAMES[h] for h in found)
            typer.echo(f"Also found {names}: run `seamspec init --hosts {','.join(found)}` to set SeamSpec up there.")
            return
        chosen = [h for h in found if typer.confirm(
            f"Set SeamSpec up for {host_installer.NAMES[h]} too (rules in AGENTS.md, its MCP config, hooks and"
            " /seamspec-* commands)?", default=True)]  # fmt: skip
    for host in chosen:
        typer.echo(f"{host_installer.NAMES[host]}:")
        for change in host_installer.install(root, host):
            typer.echo(f"  {change.status:<9} {change.path}")
    if chosen:
        typer.echo("  The hooks run `seamspec` from your PATH; start a new chat (or reload the window) to load them.")
        typer.echo(
            "  If the tool already had this folder open, restart the `seamspec` server in its MCP settings"
            " (or reload the window) so it picks up the new settings."
        )
        for host in chosen:
            for note in host_installer.SETUP_NOTES.get(host, ()):
                typer.echo(f"  {note}")


def _init_plugin(root: Path, wanted: bool | None, scope: str | None = None) -> None:
    """Offer the Claude Code plugin (SPEC §16.1). Changing Claude Code's settings needs a yes."""
    if wanted is False:
        return
    if wanted is None and not _interactive():
        typer.echo("Claude Code plugin: not checked (no terminal). Run `seamspec init --plugin` to install it.")
        return
    result = claude_plugin.precheck(root, scope or "local")
    if result is None:
        source = claude_plugin.marketplace_source()
        assert source is not None  # precheck() checked it
        if wanted is None:
            typer.echo(PLUGIN_SCREEN)
            for args in claude_plugin.commands(source, scope or "local"):
                typer.echo(f"  claude plugin {' '.join(args)}")
            typer.echo(
                f"It would be enabled in {claude_plugin.SETTINGS[scope or 'local']}"
                + (": just you, just this repository." if scope != "project" else ", for everyone in this repository.")
                + " Claude Code would also record the install in its config directory (normally"
                " ~/.claude/plugins/); nothing is turned on elsewhere."
            )
            if not typer.confirm(
                "Install the SeamSpec plugin for Claude Code in this repository?"
                " (Skip it if you don't use Claude Code.)",
                default=True,
            ):
                typer.echo("Claude Code plugin: not installed. Run `seamspec init --plugin` any time.")
                return
            if scope is None and claude_plugin.shareable(source):
                scope = "project" if typer.confirm(PLUGIN_TEAM_QUESTION, default=False) else "local"
                if scope == "project":
                    typer.echo("SeamSpec will run these instead:")
                    for args in claude_plugin.commands(source, scope):
                        typer.echo(f"  claude plugin {' '.join(args)}")
        result = claude_plugin.enable(root, scope or "local")
    typer.echo(f"Claude Code plugin: {result.status} ({result.message})")
    if result.gitignore in ("created", "updated"):
        typer.echo(f"  {result.gitignore:<9} .gitignore ({claude_plugin.SETTINGS_LOCAL})")
    if result.status == "installed":
        typer.echo("  Start a new Claude Code session (or run /reload-plugins) to load it.")
        if scope == "project":
            typer.echo(
                f"  Commit {claude_plugin.SETTINGS['project']}. Teammates also need the `seamspec` command;"
                " without it the plugin stays silent."
            )


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
        "critical": sum(1 for i in invs if isinstance(i, Invariant) and i.critical and i.status == InvStatus.LOCKED),
        "dead_ends": {s: de_counts.get(s, 0) for s in ("ACTIVE", "RETIRED")},
        "awaiting_review": inv_counts.get(InvStatus.PROPOSED.value, 0)
        + len(requests.pending_supersede_ids(store))
        + len(review_mod.pending_decisions(store)),
        "supersede_requests": sorted(requests.pending_supersede_ids(store)),
        "braindump": {
            "new_notes": len(braindump.pending(store, cfg.braindump.path, cfg.braindump.marker)),
            "planned": len(braindump.planned(store, cfg.braindump.path, cfg.braindump.marker)),
        },
        "last_verify": last_verify,
        "catches": catches.counts(store),
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
    typer.echo(
        "  invariants  "
        + "  ".join(f"{k.lower()} {v}" for k, v in inv.items())
        + (f"  (critical {data['critical']})" if data["critical"] else "")
    )
    typer.echo(f"  dead ends   active {de['ACTIVE']}  retired {de['RETIRED']}")
    lv = data["last_verify"]
    typer.echo(f"  last verify {'never' if lv is None else ('passed' if lv.get('passed') else 'FAILED')}")
    caught = data["catches"]
    if caught["stop"] or caught["commit"]:
        typer.echo(
            f"  caught      {caught['stop']} at the end of a task, {caught['commit']} at a commit (this machine)"
        )
    if data["awaiting_review"]:
        typer.echo(f"{data['awaiting_review']} awaiting review: run `seamspec review`.")
    if data["braindump"]["planned"]:
        typer.echo(
            f"{data['braindump']['planned']} planned rule(s) from {cfg.braindump.path}, waiting for their code"
            " (`seamspec drain` lists them)."
        )
    if data["braindump"]["new_notes"]:
        typer.echo(
            f"{data['braindump']['new_notes']} new note(s) in {cfg.braindump.path}: ask your agent to sort them."
        )
    if stray := braindump.below_marker_note(store.root, cfg.braindump.path, cfg.braindump.marker):
        typer.echo(stray)


@app.command()
def spec(
    out: Annotated[
        Path | None, typer.Option("--out", help="Write the document to this file (marked as generated).")
    ] = None,
    check: Annotated[
        Path | None, typer.Option("--check", help="Exit 1 if this written copy is out of date (for CI).")
    ] = None,
) -> None:
    """Print the spec this code has earned: every approved rule, generated from the ledger (§15.2)."""
    _root_dir, _cfg, store = _open()
    if out is not None and check is not None:
        raise _fail("use --out or --check, not both")
    try:
        counts = specdoc.counts(store)
        document = specdoc.render(store, generated_line=out is not None or check is not None)
    except RecordError as exc:
        raise _fail(f"bad record: {exc}") from None
    waiting = (
        f"Not in the spec: {counts.proposed} proposed rule{'' if counts.proposed == 1 else 's'} waiting for review"
        " (`seamspec review`)."
        if counts.proposed
        else None
    )
    if check is not None:
        try:
            written = check.read_text(encoding="utf-8").replace("\r\n", "\n")
        except (OSError, ValueError) as exc:
            raise _fail(f"{check}: can't read it ({exc}). Write it with `seamspec spec --out {check}`.") from None
        if written != document:
            raise _fail(f"{check} is out of date: run `seamspec spec --out {check}` and commit the result.")
        typer.echo(f"{check} is up to date ({counts.line()}).")
        return
    if out is None:
        typer.echo(document, nl=False)
        if waiting:
            typer.echo(waiting, err=True)  # beside the document, never in it
        return
    target = out if out.is_absolute() else Path.cwd() / out
    resolved = target.resolve()  # both sides resolved, so a symlinked project folder is still recognised
    if (store.root / ".seamspec").resolve() in [resolved, *resolved.parents]:
        raise _fail("the spec can't be written inside .seamspec/: that folder holds the records it is generated from")
    if target.is_dir():
        raise _fail(f"{out} is a folder: give a file name, for example `{out}/SPEC.md`")
    if target.exists():
        try:
            mine = specdoc.is_generated(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            mine = False
        if not mine:
            raise _fail(
                f"{out} exists and wasn't written by `seamspec spec`, so it is left alone. Choose another name."
            )
    try:
        atomic_write(target, document)
    except OSError as exc:  # no permission, a parent that is a file, a full disk
        raise _fail(f"{out}: can't write it ({exc})") from None
    typer.echo(f"Wrote {out}: {counts.line()}.")
    if waiting:
        typer.echo(waiting)


@app.command()
def context(
    files: Annotated[list[str], typer.Argument(help="Files you are about to change.")],
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Show the invariants and dead ends that apply to FILES, and the rules the user planned (MCP-free fallback)."""
    root, cfg, store = _open()
    try:
        cs = constraints_for(store, [str((Path.cwd() / f).resolve()) for f in files])
    except RecordError as exc:
        raise _fail(f"bad record: {exc}") from None
    if as_json:
        out = cs.to_dict()
        if plans := braindump.planned_payload(store, cfg.braindump.path, cfg.braindump.marker):
            out["planned"] = plans  # the same shape as MCP get_constraints
        typer.echo(json.dumps(out, indent=2))
        return
    shown = ", ".join(cs.files) or "(no files inside this repository)"
    plans = braindump.planned_lines(store, cfg.braindump.path, cfg.braindump.marker)
    if not (cs.locked or cs.proposed or cs.dead_ends):
        typer.echo(f"SeamSpec: no invariants or dead ends apply to {shown}.")
    else:
        typer.echo(f"SeamSpec: {shown} {'is' if len(cs.files) == 1 else 'are'} governed by:")
        typer.echo(cs.render())
    if plans:
        typer.echo("\n" + "\n".join(plans))


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
    "origin_type", "origin_ref", "scope_tags", "replace_id", "adr", "critical",
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


@app.command()
def critical(
    inv_id: Annotated[str, typer.Argument(help="Proposed or locked rule.")],
    off: Annotated[bool, typer.Option("--off", help="Clear the mark instead.")] = False,
) -> None:
    """Mark a rule critical, so the agent always sees it in full (human only). --off clears it."""
    _human_only()
    _root_dir, _cfg, store = _open()
    try:
        lifecycle.set_critical(store, inv_id, not off)
    except (lifecycle.LifecycleError, KeyError) as exc:
        raise _fail(str(exc)) from None
    typer.echo(f"{inv_id}: {'no longer critical' if off else 'critical (always shown to the agent in full)'}")


@app.command("dead-end")
def dead_end(
    from_json: Annotated[str, typer.Option("--json", help="Read the dead end as JSON from stdin ('-').")] = "-",
) -> None:
    """Record an approach that was tried and failed (agents without MCP). No approval needed."""
    if from_json != "-":
        raise _fail("only `--json -` (stdin) is supported")
    _root_dir, cfg, store = _open()
    data = _read_json_stdin()
    allowed = {"scope_paths", "approach", "failure_symptom", "related_invariant", "origin_ref"}
    if set(data) - allowed or not {"scope_paths", "approach", "failure_symptom"} <= set(data):
        raise _fail(f"expected fields: {', '.join(sorted(allowed))} (related_invariant, origin_ref optional)")
    try:
        _emit(lifecycle.log_dead_end(store, cfg, **data))
    except (lifecycle.LifecycleError, KeyError) as exc:
        _emit({"error": "invalid", "message": str(exc)})


@app.command("propose-decision")
def propose_decision(
    from_json: Annotated[str, typer.Option("--json", help="Read the decision as JSON from stdin ('-').")] = "-",
) -> None:
    """Propose a decision record with no test of its own (agents without MCP); a human decides in review."""
    if from_json != "-":
        raise _fail("only `--json -` (stdin) is supported")
    _root_dir, cfg, store = _open()
    data = _read_json_stdin()
    required = {"title", "context", "decision", "consequences", "scope_paths", "origin_text"}
    if set(data) - (required | {"origin_ref"}) or not required <= set(data):
        raise _fail(f"expected fields: {', '.join(sorted(required))} (origin_ref optional)")
    try:
        _emit(lifecycle.propose_decision(store, cfg, **data))
    except (lifecycle.LifecycleError, KeyError, TypeError) as exc:
        _emit({"error": "invalid", "message": str(exc)})


@app.command()
def drain(
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
    tidy: Annotated[
        bool, typer.Option("--tidy", help="Move sorted notes below the marker (changes your file; human only).")
    ] = False,
    dismiss: Annotated[
        list[str] | None,
        typer.Option(
            "--dismiss",
            metavar="ID=todo|exploration|planned",
            help="Set a note aside as a task, an idea, or a rule planned before its code exists; it stays in the "
            "file (repeatable; agents without MCP).",
        ),
    ] = None,
) -> None:
    """List BRAINDUMP.md notes not yet sorted. Sorting is the agent's job (`/seamspec:drain`)."""
    _root_dir, cfg, store = _open()
    path, marker = cfg.braindump.path, cfg.braindump.marker
    if dismiss:
        if tidy:
            raise _fail("use --dismiss or --tidy, not both")
        pairs = [d.partition("=") for d in dismiss]
        if any(not sep for _, sep, _ in pairs):
            raise _fail("write each as ID=todo, ID=exploration or ID=planned")
        try:
            done = braindump.dismiss(store, path, marker, [{"item_id": i, "as": k} for i, _, k in pairs])
        except (ValueError, KeyError) as exc:
            raise _fail(str(exc).strip("'\"")) from None
        typer.echo(f"Set aside {len(done)} note(s); they stay in {path}.")
        return
    if tidy:
        _human_only()
        moved = braindump.tidy(store, path, marker)
        typer.echo(f"Moved {moved} sorted note(s) below the marker in {path}." if moved else "Nothing to tidy.")
        return
    items = braindump.pending(store, path, marker)
    plans = braindump.planned(store, path, marker)
    stray = braindump.below_marker_note(store.root, path, marker)
    if as_json:
        out: dict[str, Any] = {"file": path, "pending": [{"id": i.id, "text": i.text} for i in items]}
        if plans:
            out["planned"] = [{"id": i.id, "text": i.text} for i in plans]
        if stray:
            out["below_marker"] = stray
        typer.echo(json.dumps(out, indent=2))
        return
    if braindump.location(store.root, path) is None:
        typer.echo(f"{path} points outside this repository, so SeamSpec doesn't read it.")
        return
    if braindump.read(store.root, path) is None:
        typer.echo(f"No {path} here. `seamspec init` creates one.")
        return
    if stray:
        typer.echo(f"Note: {stray}")
    if plans:
        typer.echo(f"{path}: {len(plans)} planned rule(s), waiting for their code (delete the note to drop one):")
        for item in plans:
            typer.echo(f"  {item.id}  {review_mod.cut(item.text, 100)}")
    if not items:
        typer.echo(f"{path}: nothing new to sort.")
        return
    typer.echo(f"{path}: {len(items)} note(s) not sorted yet. Ask your agent to sort them (`/seamspec:drain`).")
    for item in items:
        typer.echo(f"  {item.id}  {review_mod.cut(item.text, 100)}")


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


STAGED_NOTE = (
    "Checked what this commit records (your staged files), which differs from the files on disk. "
    "If you fixed something after `git add`, stage it again."
)


def _untrusted_message(store: Store, reason: str) -> str:
    """Why `verify` won't run here, and what to do. A clone this machine never set up (a teammate's fresh
    clone, ADR-20261019-e2f8) needs `seamspec init`, which shows what would run and asks; an agent in it
    should say so instead of quietly skipping the check (second-actor benchmark, 2026-10-19)."""
    if not trust.consent_given(store) and not (store.local / "trust.json").exists():
        return (
            f"SeamSpec isn't set up for this clone on this machine ({reason}), so its locked rules can't run "
            "here yet. Run `seamspec init` in a terminal: it shows the test commands this repository would run "
            "and asks first. Agents: tell the user this, and that CI still checks the rules on every push."
        )
    return f"This clone is not trusted ({reason}). Run `seamspec trust`."


def _verify_text(
    store: Store, report: verifier.VerifyReport, problems: list[str], gate: bool, staged: bool = False
) -> str:
    """What failed, for a human (dogfooding #11, ADR-20261013-4e9b). The short block per rule comes
    last, where the eye lands in a terminal. At a refused commit the runner's own output is left out
    for every failure the block explains; a plain `seamspec verify` and CI keep all of it, above."""
    summary, unexplained = failtext.summary(store, report)
    shown = unexplained if gate else [r for r in report.results if not r.passed]
    count = failtext.count(report)
    head = "SeamSpec: commit blocked." if gate else "SeamSpec: verification failed."
    note = [STAGED_NOTE] if staged else []
    lines = [head, *note, *problems, *report.config_failures, *(failtext.raw(r) for r in shown)]
    if summary:
        lines += ["", f"{count}:" if count else "Failed:", *summary]
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
                raise _fail(_untrusted_message(store, st.reason))
            typer.echo(f"This clone is not trusted ({st.reason}).")
            trust_cmd(show=False)
        if gate and not trust.consent_given(store):
            raise _fail("automatic test runs aren't allowed on this machine. Re-run `seamspec init`.")

    problems = journal.unjournaled_changes(store) if gate else []
    staged = False
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
                with lifecycle.harness_in_place(store, cfg, inv) as placed:  # not `staged`: that flag means git's index
                    one = verifier.run(root, cfg, [placed])
                report.results += one.results
                report.config_failures = one.config_failures
            report.passed = not report.config_failures and all(r.passed for r in report.results)
        else:
            locked = [i for i in store.load_all("inv") if isinstance(i, Invariant) and i.status == InvStatus.LOCKED]
            if changed:
                files = tree.changed_files(root)
                if files is not None:
                    locked = [i for i in locked if any(matches(i.scope.paths, f) for f in files)]
            # A commit records the staged files: when they differ from disk, check those (ADR-20261014-3b1e).
            staged = gate and not ci and snapshot.differs(root)
            if staged:
                report = _verify_staged(root, cfg, locked)
            else:
                report = verifier.run(root, cfg, locked)
                verifier.save_last(root, report)
    except (RecordError, KeyError, lifecycle.LifecycleError) as exc:
        raise _fail(str(exc)) from None

    ok = report.passed and not problems
    if gate and not ok:  # the commit check refused a commit (ADR-20261018-6e1a)
        catches.record(store, "commit", list(report.failing_ids))
    pending = len([i for i in store.load_all("inv") if i.status == InvStatus.PROPOSED])
    if as_json:
        typer.echo(json.dumps({**report.to_dict(), "journal_problems": problems, "passed": ok}, indent=2))
    else:
        ran = sum(len(r.invariant_ids) for r in report.results)
        if ok:
            typer.echo(f"SeamSpec: {ran} invariant(s) passed" + (" (on the staged files)." if staged else "."))
        else:
            typer.echo(_verify_text(store, report, problems, gate, staged), err=gate)
            if not proposed:
                typer.echo(
                    "\nFix the regression, or if the change is intentional, supersede the rule "
                    "(`seamspec supersede <id> --reason ...`).",
                    err=gate,
                )
            if gate and report.results and not staged:  # `verify --all` runs the files on disk
                typer.echo("Full test output: `seamspec verify --all`", err=True)
        if gate and pending:
            typer.echo(f"SeamSpec: {pending} item(s) awaiting review: run `seamspec review`.", err=True)
    if not ok:
        raise typer.Exit(1)


def _verify_staged(root: Path, cfg: Any, locked: list[Invariant]) -> verifier.VerifyReport:
    """Run the locked tests on a copy of what the commit records (SPEC §16.4). Fails closed when the
    copy can't be made or the run may have imported the working tree's code."""
    try:
        with snapshot.staged(root, cfg, locked) as snap:
            report = verifier.run(snap.root, cfg, locked, first_on_path=snap.first_on_path)
            if not snap.trustworthy({r.runner for r in report.results if not r.could_not_run}):
                raise snapshot.SnapshotError(snapshot.EDITABLE)
    except snapshot.SnapshotError as exc:
        raise _fail(f"commit blocked. {exc}") from None
    return report


@app.command("mcp")
def mcp_cmd() -> None:
    """Run the SeamSpec MCP server on stdio (started by the Claude Code plugin or another MCP client)."""
    from .mcp_server import run

    run()


@app.command(hidden=True)
def hook(
    host: Annotated[str, typer.Argument(help="Host adapter: claude | cursor | vscode | antigravity")],
    event: Annotated[str, typer.Argument(help="Hook event: pre-tool-use | stop | session-start | config-change")],
) -> None:
    """Internal: host hook entry point. Reads the hook payload on stdin; always exits 0."""
    if host in ("cursor", "vscode", "antigravity"):  # ADR-20261013-e8f3
        from .adapters import hosts as other_hosts

        if event not in other_hosts.EVENTS:
            typer.echo(f"seamspec hook: unknown event {event!r} for {host}", err=True)
            return
        if out := other_hosts.main(host, event):
            typer.echo(out)
        return
    if host != "claude":
        typer.echo(f"seamspec hook: unknown host {host!r} (claude, cursor, vscode, antigravity)", err=True)
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
