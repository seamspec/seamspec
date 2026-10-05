---
id: ADR-20261005-c41d
title: Resolve v0.1 spec inconsistencies before week 1
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-05
scopes: ["docs/**"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261005-c41d: Resolve v0.1 spec inconsistencies before week 1

## Context
A review of `docs/SPEC.md` after the v0.1 scope cut found places where sections still described the pre-cut design or contradicted each other. Some were plain labeling; five needed a decision before week 1 code is written against them.

## Decision

1. **CI by mode (§7.3, §9.1, §15, §16.5).** The CI workflow is a v0.1 deliverable for everyone, not only `strict`. `init` in `enforced` mode *offers* it (`[Y/n]`, or `--ci` / `--no-ci`); `strict` always installs it plus CODEOWNERS; `advisory` never does. The workflow file is identical in every mode.
2. **Directive delivery in v0.1 (§9.1, §16.1, §18).** A Claude Code plugin can't ship project instructions, so `seamspec init` writes the directive into `CLAUDE.md` between `<!-- seamspec:begin -->` / `<!-- seamspec:end -->` markers and never touches anything outside them. `doctor` reports drift. Directive rules about BRAINDUMP and the session-start nudge are marked *(v0.2)* and left out of the v0.1 block.
3. **MCP through the plugin (§14.3, §16.1).** In v0.1 Claude Code gets the MCP server from the plugin's `.mcp.json`, not a project `.mcp.json`. It starts through a separate wrapper, `bin/seamspec-mcp`, which prints an install hint to stderr and exits 1 when the CLI is missing. Hooks keep `bin/seamspec-hook`, which exits 0 silently. A silent MCP exit would only surface as a vague "failed to connect".
4. **Journal comparison rules (§11.1, §16.1).** A record absent at `HEAD` that appears as `LOCKED`, `SUPERSEDED` or `REJECTED` counts as `none → <status>` and needs a journal entry; appearing as `PROPOSED` doesn't. A deleted `LOCKED` record is always flagged, because the CLI never deletes records. An entry matches on `id`, `from` and `to`.
5. **Approval writes fingerprints only on success (§19.7, §19.8).** `approve` computes the current runner-config fingerprints, passes them to the verifier, and writes `fingerprints.json` only after the harness passes. A failed approval leaves no state behind.

Labeling-only fixes in the same change: the §8 host matrix gains a "Ships in" row and marks the session-start nudge *(v0.2)*; the Cursor and VS Code MCP configs in §14.3 are marked *(v0.2)*.

**Alternatives considered:**
- *CI in `strict` only:* rejected. CI is the only gate an agent can't skip (pre-commit has `--no-verify`), so individual users should get it by default too. Offering rather than forcing respects repos that don't use GitHub Actions.
- *Inject the directive through a `SessionStart` hook instead of `CLAUDE.md`:* deferred. It needs no file edits, but `SessionStart` is otherwise a v0.2 hook, and a visible `CLAUDE.md` block is easier for users to read and audit. Revisit with the session-start nudge in v0.2.
- *One wrapper for hooks and MCP:* rejected for the reason in decision 3.

## Enforced Invariants
None yet. Decisions 4 and 5 become invariants once `journal.py` and `lifecycle.py` exist (week 2).

## Consequences
* Week 4's CI deliverable now covers `enforced` and `strict`; `init` gains `--ci` / `--no-ci`.
* `init` must merge a marked block into `CLAUDE.md` without clobbering user content (week 1 scaffolding, tested with fixtures).
* The plugin layout has two wrappers in `bin/`.
* `verifier.run` and `check_fingerprints` take an optional `fingerprints` override.
* Not changed here: moving the red-green check (§11.4) from week 2 to week 4 was suggested in review but is a scheduling call, left open.
