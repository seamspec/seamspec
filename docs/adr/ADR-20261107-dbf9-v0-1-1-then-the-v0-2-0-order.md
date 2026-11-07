---
id: ADR-20261107-dbf9
title: 0.1.1 ships the dogfooding fixes; the order of work for 0.2.0
status: ACCEPTED
date: 2026-11-07
scopes: ["docs/SPEC.md", "docs/PROGRESS.md"]
invariants: []
supersedes: null
superseded_by: null
---

# 0.1.1 ships the dogfooding fixes; the order of work for 0.2.0

## Context

0.1.0 was published on 2026-10-27. Since then, the owner dogfooded it on their own project, SessionWalk, in Claude Code and Antigravity. That turned up a blocker for upgrades (the Claude Code plugin stayed on the old tag) and a run of smaller problems. The v0.2 list in §22 dates from 2026-10-11 (ADR-20261011-0995), before launch and before any outside use.

On 2026-11-05 the owner accepted this order: ship a 0.1.1 with the fixes first, then 0.2.0 in a new order.

## Decision

**0.1.1, a patch release** with what dogfooding found (PRs #110 to #117): the plugin follows an upgrade (ADR-20261105-bf19); Antigravity is offered for a `GEMINI.md` and its machine-specific config stays out of git (ADR-20261105-844f); a warning before a personal email is approved into a rule, and local checks of a locked rule's details (ADR-20261105-a7d2); a test that stops with an error isn't called a regression (ADR-20261105-0576); the reviewer's "My read" follows the gaps it lists (ADR-20261105-e2c9); SeamSpec's own host files are guarded (ADR-20261105-9d3f); `init` asks outside git (ADR-20261105-5c1d); agents are told when to record a decision (ADR-20261105-7a4e).

**Moved from 0.1.1 to 0.2.0:** making `verify --proposed` run the way the commit check does. The commit check runs on a copy of the staged files, while a proposed test usually checks code that isn't staged yet, so running proposals that way would fail correct tests. The fix needs a design (an opt-in staged run, or a hint when a newly approved rule fails at its first commit), and the current behavior gives a confusing failure, never a wrong pass.

**0.2.0, in this order:**

1. **More presets: jest, Go, Rust (cargo), `custom`** (§12A.2). Today only pytest and vitest projects can use SeamSpec at all; this is the widest gap for new users.
2. **Rules from an existing notes file.** The benchmark found a well-kept notes file remembers rules as well as SeamSpec (ADR-20261013-e2b6); what SeamSpec adds is enforcement. Most projects already have a `CLAUDE.md` or `AGENTS.md`, so turning its agreements into proposed, tested rules is the shortest path from "remembered" to "enforced".
3. **OpenSpec importer** (`origin.type = "import"`). Still wanted, for teams that write specs first, a smaller audience than the first two.
4. **Remaining host work:** edit-time context and edit protection on Cursor, VS Code and Antigravity. It needs each tool's edit-tool names, read from hands-on logs, so it is sized before it is scheduled.

Also in 0.2.0, smaller: `verify --proposed` and the commit check (above); decisions in `seamspec context`, the CLI fallback (ADR-20261105-7a4e). Considered, not committed: a check that runs a proposed test a few times and warns if results differ (flaky tests).

**Moved out of 0.2.0, to Later:** MCP elicitation for `run_proposed = "ask"` (the agent's shell already asks before `verify --proposed` runs, and nobody has asked for it) and the `npx seamspec` wrapper (`uv tool install seamspec` works for JavaScript projects too, and a wrapper is another package to publish and maintain).

**Waiting, in Later:** per-rule risk levels, drift checks, rules that span repositories, and the blind-spot check (a rule's test that skips new code it governs). Each needs a design, and none has been asked for by a user yet.

This amends the v0.2 order in ADR-20261011-0995.

## Enforced Invariants

None new.

## Consequences

- 0.1.1 is a patch: no new features beyond the fixes, and existing projects get the new wording by rerunning `seamspec init`.
- The v0.2 tracking issue (#7) is reordered to match.
- SessionWalk's own feedback ("4–5 proposals at once feel heavy; fewer, higher-value rules give most of the protection") is a candidate for 0.2.0 sizing, not yet scheduled.
