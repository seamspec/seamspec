---
id: ADR-20261105-7a4e
title: Agents are told when to record a decision
status: ACCEPTED
date: 2026-11-05
scopes: ["seamspec/templates/directive.md", "seamspec/templates/commands/checkpoint.md", "seamspec/templates/commands/_footer.md", "seamspec/mcp_server.py"]
invariants: []
supersedes: null
superseded_by: null
---

# Agents are told when to record a decision

## Context

On SessionWalk, `.seamspec/adrs/` stayed empty across four milestones, though real design choices were made (deferring a feature after measuring it, choosing representations, drawing module boundaries). `propose_decision` was mentioned only in the drain command, for sorting `BRAINDUMP.md`. The protocol block in `CLAUDE.md` and `AGENTS.md` told agents when to propose a rule and when to log a dead end, but never when to record a decision, and neither did the checkpoint. The SessionWalk agent pointed this out.

A decision is worth having: the MCP `get_constraints` tool already lists decisions scoped to the files it is asked about, so a recorded decision reaches every later session that edits those files.

## Decision

- **Protocol rule 3** gains a sentence: when the user and the agent settle a design choice that shapes future work on specific files, and it is a rationale or trade-off rather than something a test can check or a failed attempt, call `propose_decision` scoped to those files. The rule numbers stay the same, since the SPEC and skills refer to them.
- **The checkpoint** gains step 6, which records such choices made in the session, and says how they differ from a rule (step 4) and a dead end (step 5).
- **The shared command footer** lists `seamspec propose-decision --json -` among the CLI fallbacks.
- **The MCP tool's description** names it a design decision for these files (a trade-off, no test). It stays short: the tool definitions have a token budget, and the guidance belongs in the protocol.

## Enforced Invariants

None new.

## Consequences

- Decisions get recorded as they are made, and a person still accepts each one in `seamspec review`. The review queue can grow faster; `proposals.max_pending` already caps it (ADR-20261014-8a57).
- Existing projects get the wording when they rerun `seamspec init` (`doctor` reports the block as outdated until then).
- Limit: the CLI fallback `seamspec context` lists rules and dead ends but not decisions, so an agent without SeamSpec's MCP tools doesn't see them. A follow-up.
