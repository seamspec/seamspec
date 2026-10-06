# Architecture Decision Records

Decisions that **change or add to** [`docs/SPEC.md`](../SPEC.md) are recorded here. Plain implementation detail doesn't need an ADR.

Decisions made before the build started (up to 2026-10-05) are in SPEC §26 "Resolved Decisions".

## When to write one

| Change | ADR? |
|---|---|
| Behavior, format, CLI/MCP surface, config key, schema or default differs from SPEC | **Yes**, and update SPEC in the same commit |
| Something new that SPEC doesn't cover | **Yes**, and add it to SPEC |
| A SPEC item moves between v0.1 / v0.2 / Later | **Yes** |
| A change to the build process (how we track work, review, release) | **Yes** |
| Internal refactor, naming inside a module, test layout, bug fix that matches SPEC | No |

## Format

Same as SeamSpec's own ADRs (SPEC §10.3), so these can move into `.seamspec/adrs/` in week 3 without conversion.

- **File name:** `ADR-YYYYMMDD-xxxx-short-slug.md`, where `xxxx` is 4 random hex characters (`python3 -c "import secrets; print(secrets.token_hex(2))"`).
- **Frontmatter:** `id`, `title`, `status` (`PROPOSED | ACCEPTED | SUPERSEDED | REJECTED`), `date`, `scopes`, `invariants`, `supersedes`, `superseded_by`.
- **Sections:** Context, Decision (include alternatives considered), Enforced Invariants, Consequences.
- To replace a decision, write a new ADR with `supersedes:` set, and set `status: SUPERSEDED` + `superseded_by:` on the old one. Never delete an ADR.

## Index

| ID | Title | Status |
|---|---|---|
| [ADR-20261005-ae6e](ADR-20261005-ae6e-build-directly-dogfood-from-week-3.md) | Build SeamSpec directly from SPEC.md; dogfood from week 3 | ACCEPTED |
| [ADR-20261005-c41d](ADR-20261005-c41d-v01-consistency-fixes.md) | Resolve v0.1 spec inconsistencies before week 1 | ACCEPTED |
| [ADR-20261005-2565](ADR-20261005-2565-committed-progress-log.md) | Track progress in a committed PROGRESS.md, with CLAUDE.md as the agent entry point | ACCEPTED |
| [ADR-20261005-6f2a](ADR-20261005-6f2a-week1-implementation-decisions.md) | Week 1 implementation decisions (schemas, config strictness, store, context, spec listings) | ACCEPTED |
| [ADR-20261005-d8bc](ADR-20261005-d8bc-branches-and-prs.md) | All changes land through branches and pull requests | ACCEPTED |
| [ADR-20261005-4b1e](ADR-20261005-4b1e-verifier-findings.md) | Verifier fixes found by running real pytest and vitest | ACCEPTED |
| [ADR-20261005-9c1a](ADR-20261005-9c1a-lifecycle-and-journal.md) | Lifecycle implementation; journal flags moves back to PROPOSED | ACCEPTED |
| [ADR-20261005-8e80](ADR-20261005-8e80-verify-trust-pre-commit.md) | verify CLI, consent and trust, pre-commit gate | ACCEPTED |
| [ADR-20261005-3adc](ADR-20261005-3adc-publishing-needs-owner-go.md) | Publishing to PyPI or npm needs the owner's explicit go-ahead | ACCEPTED |
| [ADR-20261005-b7e2](ADR-20261005-b7e2-review-and-red-green.md) | seamspec review, red-green check, and explicit runner-config confirmation | ACCEPTED |
| [ADR-20261005-c076](ADR-20261005-c076-request-copilot-review.md) | The agent requests a Copilot review on every PR it opens | ACCEPTED |
| [ADR-20261005-5009](ADR-20261005-5009-claude-code-hooks.md) | Claude Code hook adapter, aligned with the current hooks reference | ACCEPTED |
