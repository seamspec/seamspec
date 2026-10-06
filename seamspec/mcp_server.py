"""SeamSpec MCP server (SPEC §14): a thin, typed interface over the core for agents.

v0.1: 5 tools (`get_constraints`, `propose_invariant`, `log_dead_end`, `request_supersede`, `verify`)
and 2 resources (`seamspec://adrs`, `seamspec://adrs/{adr_id}`). Every tool has a CLI equivalent.
Tool descriptions stay short: their definitions sit in the model's context in every session.

The MCP server never runs unapproved code (§12.4.3): `propose_invariant` only writes, and `verify`
runs LOCKED rules only, and only where automatic runs are allowed (consent + trust).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict

from mcp.server.mcpserver import MCPServer

from .core import adr, lifecycle, tree, verifier
from .core.config import Config, ConfigError, load_config
from .core.context import constraints_for
from .core.models import Invariant, InvStatus
from .core.root import RootNotFound, find_root
from .core.scope import matches
from .core.store import RecordError, Store
from .core.trust import execution_permitted

INSTRUCTIONS = (
    "SeamSpec keeps this repo's human-approved rules (LOCKED invariants), each backed by a test, and "
    "approaches that already failed (dead ends). Call get_constraints before editing files. Propose "
    "rules for behavior worth protecting; only humans approve them (`seamspec review`)."
)

mcp = MCPServer(name="seamspec", instructions=INSTRUCTIONS)


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
    def discover(cls) -> Services:
        """Resolve the project per call ($SEAMSPEC_ROOT, else walk up from the server's cwd)."""
        root = find_root()
        return cls(root, load_config(root), Store(root))


def _with_services(fn) -> dict[str, Any]:
    try:
        return fn(Services.discover())
    except (RootNotFound, ConfigError) as exc:
        return {"error": "not_a_seamspec_project", "message": str(exc)}
    except (lifecycle.LifecycleError, RecordError, KeyError, ValueError) as exc:
        return {"error": "invalid", "message": str(exc)}


def _runner_hints(svc: Services, rels: list[str]) -> list[dict[str, str]]:
    """Which runner to use for these files, and where its tests live (§12A.6)."""
    hints = []
    for name, runner in sorted(svc.cfg.runners.items()):
        if not runner.paths or any(matches(runner.paths, r) for r in rels):
            hints.append({"runner": name, "test_location": runner.harness_path("<id>")})
    return hints


@mcp.tool()
def get_constraints(files: list[str]) -> dict[str, Any]:
    """Locked rules, proposed rules and failed approaches that apply to these files. Call before editing."""

    def run(svc: Services) -> dict[str, Any]:
        cs = constraints_for(svc.store, [str(svc.root / f) if not Path(f).is_absolute() else f for f in files])
        out = cs.to_dict()
        out["summary"] = cs.render() or "No SeamSpec rules or dead ends apply to these files."
        out["runners"] = _runner_hints(svc, cs.files)
        return out

    return _with_services(run)


@mcp.tool()
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
) -> dict[str, Any]:
    """Propose a rule with a focused behavior-level test. Does NOT run the test: afterwards run
    `seamspec verify --proposed <id>` with your shell. Use replace_id to update your own proposal.
    On error "queue_full", stop proposing and ask the user to run `seamspec review`."""

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
        )

    return _with_services(run)


@mcp.tool()
def log_dead_end(
    scope_paths: list[str], approach: str, failure_symptom: str, related_invariant: str | None = None
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
        )
    )


@mcp.tool()
def request_supersede(invariant_id: str, reason: str, replacement_id: str | None = None) -> dict[str, Any]:
    """Ask the user to retire or replace a LOCKED rule whose requirement changed. Never edit its test instead."""
    return _with_services(lambda svc: lifecycle.request_supersede(svc.store, invariant_id, reason, replacement_id))


@mcp.tool()
def verify(scope: Literal["changed", "all"] = "all") -> dict[str, Any]:
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

    return _with_services(run)


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
