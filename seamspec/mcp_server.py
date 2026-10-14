"""SeamSpec MCP server (SPEC §14): a thin, typed interface over the core for agents.

v0.1: 6 tools (`get_constraints`, `propose_invariant`, `log_dead_end`, `request_supersede`, `verify`,
`open_review`) and 2 resources (`seamspec://adrs`, `seamspec://adrs/{adr_id}`). Every tool has a CLI equivalent.
Tool descriptions stay short: their definitions sit in the model's context in every session.

The MCP server never runs unapproved code (§12.4.3): `propose_invariant` only writes, and `verify`
runs LOCKED rules only, and only where automatic runs are allowed (consent + trust).
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlparse
from urllib.request import url2pathname

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.resolve import ListRoots, Resolve
from mcp.server.request_state import RequestStateSecurity
from mcp_types import InputRequiredResult, ListRootsResult
from typing_extensions import TypedDict  # pydantic needs this one on Python < 3.12

from . import brief, chat_review
from .core import adr, braindump, lifecycle, runners, tree, verifier
from .core.config import Config, ConfigError, RunnerCfg, load_config
from .core.context import constraints_for
from .core.models import Invariant, InvStatus
from .core.root import CONFIG_REL, RootNotFound, project_at
from .core.scope import matches
from .core.store import RecordError, Store
from .core.trust import execution_permitted

INSTRUCTIONS = (
    "SeamSpec keeps this repo's human-approved rules (LOCKED invariants), each backed by a test, and "
    "approaches that already failed (dead ends). Call get_constraints before editing files. Propose "
    "rules for behavior worth protecting; only humans approve them (`seamspec review`)."
)

# Dialog state rides the client between rounds, sealed by the SDK; an hour leaves time to read a test.
mcp = MCPServer(
    name="seamspec", instructions=INSTRUCTIONS, request_state_security=RequestStateSecurity.ephemeral(ttl=3600)
)


class AdrDraft(TypedDict):
    context: str
    decision: str
    consequences: list[str]


@dataclass
class Services:
    root: Path
    cfg: Config
    store: Store

    @classmethod
    def discover(cls, roots: ListRootsResult | None = None, hints: list[str] | None = None) -> Services:
        """Resolve the project per call (ADR-20261011-d4a1). First where the server was started:
        $SEAMSPEC_ROOT (the plugin sets it to the folder the session was *launched* in), then the
        server's own folder. A session moved to another folder launched somewhere else, so if neither
        is a SeamSpec project, look at the session's folders the client reported (`roots`) and at
        absolute file paths in the call (`hints`). Exactly one project there is the answer."""
        root = _local_root()
        if root is None:
            found = list(dict.fromkeys(p for p in map(project_at, _paths(roots, hints)) if p is not None))
            if len(found) > 1:
                raise RootNotFound(
                    f"This session has {len(found)} SeamSpec projects open ({', '.join(map(str, found))}), and "
                    "SeamSpec's tools can't tell which one you mean. Start a session in the one you want."
                )
            if not found:
                raise RootNotFound(_not_found_message())
            root = found[0]
        return cls(root, load_config(root), Store(root))


def _local_root() -> Path | None:
    env = os.environ.get("SEAMSPEC_ROOT")
    for start in ([Path(env)] if env else []) + [Path.cwd()]:
        found = project_at(start)
        if found is not None:
            return found
    return None


def _paths(roots: ListRootsResult | None, hints: list[str] | None) -> list[Path]:
    paths: list[Path] = []
    for root in roots.roots if roots is not None else []:
        url = urlparse(str(root.uri))
        if url.scheme == "file":
            paths.append(Path(url2pathname(url.path)))  # url2pathname decodes %xx itself
    paths += [Path(h) for h in hints or [] if Path(h).is_absolute()]
    return paths


def _not_found_message() -> str:
    env = os.environ.get("SEAMSPEC_ROOT")
    started = (
        f"the folder this session started in ({env})" if env else f"the folder they were started in ({Path.cwd()})"
    )
    return (
        f"SeamSpec's tools are tied to {started}, which has no {CONFIG_REL.as_posix()}, and no other folder of "
        "this session is a SeamSpec project. Start a new session in your project folder, or run `seamspec init` there."
    )


def _roots_if_needed(ctx: Context) -> Any:
    """Ask the client for the session's folders only when the project can't be found without them,
    so the usual call makes no extra round trip. A client without `roots` is simply not asked."""
    if _local_root() is not None:
        return None
    capabilities = ctx.client_capabilities
    if capabilities is None or capabilities.roots is None:
        return None
    return ListRoots()


# Filled in by the server, never by the model: it isn't part of a tool's input schema.
SessionRoots = Annotated[ListRootsResult | None, Resolve(_roots_if_needed)]


def _with_services(fn, roots: ListRootsResult | None = None, hints: list[str] | None = None) -> dict[str, Any]:
    try:
        return fn(Services.discover(roots, hints))
    except (RootNotFound, ConfigError) as exc:
        return {"error": "not_a_seamspec_project", "message": str(exc)}
    except (lifecycle.LifecycleError, RecordError, KeyError, ValueError) as exc:
        return {"error": "invalid", "message": str(exc)}


def _runner_hints(svc: Services, rels: list[str]) -> list[dict[str, str]]:
    """Which runner to use for these files, where its tests live, how they import the project, and
    which program the runner's command resolves to (§12A.6, ADR-20261011-e7c5)."""
    hints = []
    for name, runner in sorted(svc.cfg.runners.items()):
        if not runner.paths or any(matches(runner.paths, r) for r in rels):
            hint = {"runner": name, "test_location": runner.harness_path("<id>")}
            if text := runners.import_hint(svc.root, name):
                hint["import_hint"] = text
            hint["command"] = _command_note(svc, runner)
            hints.append(hint)
    return hints


def _command_note(svc: Services, runner: RunnerCfg) -> str:
    """Where the runner's program comes from, found the way the verifier finds it (§12.4.7). An agent
    reading `cmd = ["pytest", ...]` in config.toml can't know SeamSpec looks in the project's own tool
    folders first, without activation."""
    command = runner.cmd[0]
    env = verifier.build_env(svc.cfg, root=svc.root, overrides=runner.env)
    if "/" in command or os.sep in command:  # a path: run as written, from the project root
        path = Path(command) if Path(command).is_absolute() else svc.root / command
        if not (path.is_file() and os.access(path, os.X_OK)):
            return (
                f"`{command}` (the runner's command in config.toml) doesn't exist in the project or isn't "
                "executable: rule tests can't run until that is fixed."
            )
        return f"`{command}` is run as written in config.toml, from the project root."

    activated = bool(env.get("VIRTUAL_ENV"))
    places = (
        "the activated virtualenv (VIRTUAL_ENV), which wins over the project's .venv and venv, and node_modules/.bin"
        if activated
        else "the project's .venv, venv and node_modules/.bin"
    )
    found = shutil.which(command, path=env.get("PATH", ""))
    if found is None:
        return f"`{command}` was not found in {places}, nor on PATH: install it before running rule tests."
    try:
        shown = Path(found).resolve().relative_to(svc.root.resolve()).as_posix()
    except ValueError:
        shown = found
    how = "It was looked up in" if activated else "SeamSpec looks in"
    return (
        f"`{command}` resolves to {shown}. {how} {places} first, without activation needed, then on PATH, "
        "so config.toml needs no change."
    )


def _adr_summaries(svc: Services, rels: list[str], linked: set[str]) -> list[dict[str, str]]:
    """Decision records for these files: scoped to them, or linked from a matching rule (§14.1)."""
    out = []
    for record in adr.load_all(svc.store):
        if record.status in ("REJECTED", "SUPERSEDED"):
            continue
        if record.id in linked or (record.scopes and any(matches(record.scopes, r) for r in rels)):
            out.append({"id": record.id, "title": record.title, "status": record.status})
    return out


@mcp.tool(structured_output=False)
def get_constraints(files: list[str], roots: SessionRoots = None) -> dict[str, Any]:
    """Locked rules, proposed rules, failed approaches and decisions that apply to these files. Call before editing."""

    def run(svc: Services) -> dict[str, Any]:
        cs = constraints_for(svc.store, [str(svc.root / f) if not Path(f).is_absolute() else f for f in files])
        out = cs.to_dict()
        out["summary"] = cs.render() or "No SeamSpec rules or dead ends apply to these files."
        linked = {i.adr_id for i in cs.locked + cs.proposed if i.adr_id}
        out["adrs"] = _adr_summaries(svc, cs.files, linked)
        out["runners"] = _runner_hints(svc, cs.files)
        return out

    return _with_services(run, roots, files)


@mcp.tool(structured_output=False)
def propose_invariant(
    title: str,
    assertion: str,
    scope_paths: list[str],
    runner: str,
    harness_code: str,
    origin_text: str,
    origin_type: Literal["prompt", "braindump", "manual"] = "prompt",
    origin_ref: str | None = None,
    scope_tags: list[str] | None = None,
    replace_id: str | None = None,
    adr: AdrDraft | None = None,
    critical: bool = False,
    roots: SessionRoots = None,
) -> dict[str, Any]:
    """Propose a rule with a focused behavior-level test. Does NOT run the test: afterwards run
    `seamspec verify --proposed <id>` with your shell. Use replace_id to update your own proposal.
    critical: suggest it always be shown in full (the user decides). On error "queue_full", stop
    proposing and ask the user to run `seamspec review`."""

    def run(svc: Services) -> dict[str, Any]:
        return lifecycle.propose_invariant(
            svc.store,
            svc.cfg,
            title=title,
            assertion=assertion,
            scope_paths=scope_paths,
            runner=runner,
            harness_code=harness_code,
            origin_text=origin_text,
            origin_type=origin_type,
            origin_ref=origin_ref,
            scope_tags=scope_tags,
            replace_id=replace_id,
            adr_draft=adr,
            critical=critical,
        )

    return _with_services(run, roots)


@mcp.tool(structured_output=False)
def log_dead_end(
    scope_paths: list[str],
    approach: str,
    failure_symptom: str,
    related_invariant: str | None = None,
    origin_ref: str | None = None,
    roots: SessionRoots = None,
) -> dict[str, Any]:
    """Record an approach that was tried and failed, with the evidence, so it isn't retried."""
    return _with_services(
        lambda svc: lifecycle.log_dead_end(
            svc.store,
            svc.cfg,
            scope_paths=scope_paths,
            approach=approach,
            failure_symptom=failure_symptom,
            related_invariant=related_invariant,
            origin_ref=origin_ref,
        ),
        roots,
    )


@mcp.tool(structured_output=False)
def propose_decision(
    title: str,
    context: str,
    decision: str,
    consequences: list[str],
    scope_paths: list[str],
    origin_text: str,
    origin_ref: str | None = None,
    roots: SessionRoots = None,
) -> dict[str, Any]:
    """Propose a decision (ADR) with no test of its own; the user decides in `seamspec review`."""
    return _with_services(
        lambda svc: lifecycle.propose_decision(
            svc.store,
            svc.cfg,
            title=title,
            context=context,
            decision=decision,
            consequences=consequences,
            scope_paths=scope_paths,
            origin_text=origin_text,
            origin_ref=origin_ref,
        ),
        roots,
    )


@mcp.tool(structured_output=False)
def braindump_pending(
    dismiss: dict[str, Literal["todo", "exploration"]] | None = None, roots: SessionRoots = None
) -> dict[str, Any]:
    """Unsorted BRAINDUMP.md notes. dismiss: {note id: "todo" | "exploration"}. Sort the rest with
    propose_invariant, propose_decision or log_dead_end, origin_ref = the note id."""

    def run(svc: Services) -> dict[str, Any]:
        path, marker = svc.cfg.braindump.path, svc.cfg.braindump.marker
        dismissals = [{"item_id": k, "as": v} for k, v in (dismiss or {}).items()]
        done = braindump.dismiss(svc.store, path, marker, dismissals)
        items = braindump.pending(svc.store, path, marker)
        out: dict[str, Any] = {"file": path, "pending": [{"id": i.id, "text": i.text} for i in items]}
        if done:
            out["dismissed"] = done
        if braindump.read(svc.root, path) is None:
            out["note"] = f"There is no {path} in this project."
        return out

    return _with_services(run, roots)


@mcp.tool(structured_output=False)
def request_supersede(
    invariant_id: str, reason: str, replacement_id: str | None = None, roots: SessionRoots = None
) -> dict[str, Any]:
    """Ask the user to retire or replace a LOCKED rule whose requirement changed. Never edit its test instead."""
    return _with_services(
        lambda svc: lifecycle.request_supersede(svc.store, invariant_id, reason, replacement_id), roots
    )


@mcp.tool(structured_output=False)
def verify(scope: Literal["changed", "all"] = "all", roots: SessionRoots = None) -> dict[str, Any]:
    """Run the LOCKED rules' tests (all, or those whose scope matches changed files). Never runs proposals."""

    def run(svc: Services) -> dict[str, Any]:
        allowed, why = execution_permitted(svc.store, svc.cfg)
        if not allowed:
            return {"error": "not_permitted", "message": f"SeamSpec can't run tests here: {why}."}
        locked = [i for i in svc.store.load_all("inv") if isinstance(i, Invariant) and i.status == InvStatus.LOCKED]
        if scope == "changed":
            files = tree.changed_files(svc.root)
            if files is not None:
                locked = [i for i in locked if any(matches(i.scope.paths, f) for f in files)]
        report = verifier.run(svc.root, svc.cfg, locked)
        verifier.save_last(svc.root, report)
        return {
            "passed": report.passed,
            "checked": [i.id for i in locked],
            "failing_ids": report.failing_ids,
            "incomplete": report.incomplete,
            "problems": report.integrity_failures + report.config_failures,
            "failures": [
                {"runner": r.runner, "ids": r.failed_ids or r.invariant_ids, "output": r.output}
                for r in report.results
                if not r.passed
            ],
        }

    return _with_services(run, roots)


@mcp.tool(structured_output=False)
def open_review(ctx: Context, ids: list[str] | None = None) -> dict[str, Any] | InputRequiredResult:
    """Show the user SeamSpec's review dialogs (proposed rules, supersede requests, new dead ends) so they
    can decide in chat, if this project turned chat approvals on. Only the user answers; you get the outcomes."""

    def run(svc: Services) -> dict[str, Any] | InputRequiredResult:
        if not svc.cfg.review.chat_approvals:
            return {"error": "chat_approvals_off", "message": "Chat approvals are off here ([review] chat_approvals). "
                    + chat_review.FALLBACK}  # fmt: skip
        if not chat_review.can_show_dialogs(ctx.protocol_version, ctx.client_capabilities):
            return {
                "error": "no_dialogs",
                "message": "This chat can't show SeamSpec's dialogs. " + chat_review.FALLBACK,
            }
        params = ctx.session.client_params
        info = params.client_info if params else None
        client = f"{info.name} {info.version}" if info else None
        return chat_review.step(svc.store, svc.cfg, ids, ctx.request_state, ctx.input_responses, client,
                                [svc.root, Path.cwd()])  # fmt: skip

    return _with_services(run)


@mcp.tool(structured_output=False)
def review_material(ids: list[str] | None = None, roots: SessionRoots = None) -> dict[str, Any]:
    """Read-only, runs nothing. What waits for human review, with SeamSpec's facts about each test
    and the code changes in its scope. For SeamSpec's reviewer agent."""

    def run(svc: Services) -> dict[str, Any]:
        return brief.material(svc.store, ids)

    return _with_services(run, roots)


@mcp.resource("seamspec://adrs", description="One line per decision record: id, title, status, scopes.")
def adrs_summary() -> str:
    try:
        return adr.summary(Services.discover().store)
    except (RootNotFound, ConfigError) as exc:
        return f"Not a SeamSpec project: {exc}"


@mcp.resource("seamspec://adrs/{adr_id}", description="A decision record in full (Markdown).")
def adr_text(adr_id: str) -> str:
    try:
        record = adr.get(Services.discover().store, adr_id)
    except (RootNotFound, ConfigError) as exc:
        return f"Not a SeamSpec project: {exc}"
    except (KeyError, adr.AdrError):
        return f"No decision record {adr_id}."
    assert record.path is not None
    return record.path.read_text(encoding="utf-8")


def run() -> None:
    mcp.run(transport="stdio")
