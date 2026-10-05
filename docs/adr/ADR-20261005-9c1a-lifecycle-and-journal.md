---
id: ADR-20261005-9c1a
title: Lifecycle implementation; journal flags moves back to PROPOSED
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-05
scopes: ["seamspec/core/lifecycle.py", "seamspec/core/journal.py", "seamspec/core/adr.py", "seamspec/core/redact.py", "seamspec/cli.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261005-9c1a: Lifecycle implementation; journal flags moves back to PROPOSED

## Context
Week 2's second slice implements the invariant and dead-end lifecycle (SPEC §11), the approval journal (§11.1), supersede requests (§11.2), ADR files (§10.3) and the CLI commands `propose`, `dead-end`, `approve`, `reject`, `supersede` and `retire-dead-end` (§15). Implementing the journal check exposed a hole in the rules ADR-20261005-c41d wrote into §11.1.

## Decision

1. **Correction to ADR-20261005-c41d decision 4.** Its table exempted every change *to* `PROPOSED`. An agent could then edit a `LOCKED` record back to `PROPOSED` with Bash, and the rule would silently drop out of verification (only `LOCKED` invariants run) without being flagged. Now only `absent → PROPOSED` and `PROPOSED → PROPOSED` are exempt; any other change needs the journal to explain it. The CLI never moves a record back to `PROPOSED`, so such a change is always flagged.
2. **The journal matches chains, not single entries.** A rule approved and then superseded before the next commit is `absent → SUPERSEDED` against `HEAD`, which no single entry matches. The check accepts any chain of journaled transitions from the `HEAD` status (absent counts as `PROPOSED`) to the current one.
3. **Redaction covers every origin.** `origin.text` and dead-end `failure_symptom` pass through `redact()` whenever `braindump.redact_secrets` is on (the default), not only for braindump items. Chat prompts carry secrets as often as notes do.
4. **All human-only commands share one terminal check** (`approve`, `reject`, `supersede`, `retire-dead-end`), with the same `SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE=1` override. The agent's supersede path is `seamspec supersede <id> --request --reason ...`, which needs no terminal and changes no record.
5. **`seamspec approve <id>` prints the full test and asks for a yes** before running it, matching `review` (§12.4.3 rule 4).
6. **ADR frontmatter values are JSON** (valid YAML flow style), so no YAML dependency is needed. The parser also reads this repo's hand-written `docs/adr/` files, which a test checks ahead of the week 3 move into `.seamspec/adrs/`.

**Alternatives considered:**
- *Keep the c41d table as written:* rejected; it leaves a silent way to disable a rule.
- *Add a YAML library for ADR frontmatter:* rejected; SeamSpec writes the files, and the JSON subset keeps the dependency list short.

## Enforced Invariants
None yet. Candidates for week 3: "a LOCKED record moved back to PROPOSED outside the CLI is flagged" and "a failed approval writes nothing".

## Consequences
* SPEC §11.1 (journal table and matching rule), §19.8 (now a contract) and §21 are updated in the same PR.
* `seamspec status` counts pending supersede requests in `awaiting_review` and lists them as `supersede_requests`.
* The review TUI, red-green check, consent screen, `trust`, `verify` CLI and pre-commit follow in the next Week 2 slices.
