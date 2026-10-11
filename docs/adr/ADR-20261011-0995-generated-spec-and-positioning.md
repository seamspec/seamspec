---
id: ADR-20261011-0995
title: A spec generated from the ledger; positioning and order of work after dogfooding
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-11
scopes: ["seamspec/cli.py", "seamspec/adapters/claude.py", "docs/SPEC.md", "README.md"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261011-0995: A spec generated from the ledger; positioning and order of work after dogfooding

> **Status: ACCEPTED** as a plan (the owner said yes on 2026-10-11). Nothing is built yet.

## Context

After two days of dogfooding on a real project, the owner asked how SeamSpec will be received next to spec-first tools such as OpenSpec and Kiro. From their public descriptions (READMEs and docs only; clean room):

- **OpenSpec** and **Kiro** work *before* the code: the agent drafts a proposal or requirements, a design and a task list, the human corrects those documents, and the agent then builds from them. Nothing in their public docs says a build fails when the agent departs from the documents; OpenSpec's docs say archive and verify warn, they don't block.
- **SeamSpec** works *after* the code: when a behavior works, a human approves a rule with a test, and hooks, pre-commit and CI fail when it breaks.

Three things follow:

1. **The name invites the wrong comparison.** SeamSpec has "Spec" in its name and writes no spec, so people will judge it on the spec-first tools' job.
2. **The owner's original idea behind the name** was: *code first, the spec builds up afterwards from what you chose to protect*. The ledger already holds that spec, one plain-language rule at a time, but only as separate JSON records. Nobody can read it as one document.
3. **The benchmark's condition E** (ADR-20261007-e1a7) showed that plain notes match SeamSpec's memory with a careful model. What notes and spec documents don't give is approval, proof by test, and enforcement.

The owner also used a "braindump" without the feature: the dogfooding project's plan has a section *"SeamSpec invariants to propose once built"*, and the agent proposed those rules as their code landed.

## Decision

### 1. `seamspec spec`: the spec the code has earned

A new command prints a readable document **generated from the ledger**:

- **Grouped by area** of the code (the same area rule as the session-start summary, §16.1).
- **Each LOCKED rule** in plain language: title, the rule's own text, where it applies, who approved it and when, where it was decided (`decided_via`), its test file, and its linked decision record.
- **Retired rules:** SUPERSEDED ones, with the reason and what replaced them.
- **Tried and failed:** active dead ends, with why they failed.
- **Not included:** PROPOSED rules (a count only). The spec is what a human approved.

**Single source, as in ADR-20261007-ac04.** The document is generated and never edited by hand:
- By default it prints to the terminal. `--out FILE` writes it, with a "generated, do not edit" line at the top.
- `init` writes no spec file, agents don't read one (they use `get_constraints` and the session-start summary), and nothing updates one automatically.
- `--check FILE` exits 1 when a written copy is out of date, for teams that choose to commit one and want CI to catch drift.

SeamSpec still writes **no specs up front**. That is the job of the spec-first tools and of a project's own plan.

### 2. Positioning

SeamSpec is pitched as **a regression guard for agent-written code that works alongside spec tools**, not as spec-driven development: *"OpenSpec or Kiro says what to build; SeamSpec makes sure it stays built, and gives you the spec your code has earned, every line backed by a test."* The README and the demo lead with enforcement (the block, the supersede question) and the generated spec.

### 3. Order of work

1. **Fix the dogfooding bugs** (red-green with editable installs first; then the CI template's install source, the MCP server following the session's folder, and the import and runner hints for `src/` layouts), together with the readable review (ADR-20261011-8013).
2. **Finish dogfooding** on the owner's project, used as a vehicle for SeamSpec only: get a rule to catch a real mistake, and try the supersede flow.
3. **Week 5:** the benchmark, `seamspec spec`, and the README with the positioning above.
4. **v0.2**, in this order: the **OpenSpec importer** (moved up from "Later"), more hosts, the "critical" rule marking (ADR-20261007-ac04), then BRAINDUMP.

### 4. A list of intended rules, before BRAINDUMP

Until BRAINDUMP exists, the protocol block and the `checkpoint` skill will say (built with step 1): *if the project keeps a list of rules it intends to lock (a section of a plan, or `BRAINDUMP.md`), propose each one when its code exists and works.* No parsing and no new files: the agent reads the list like any other project document.

**Alternatives considered:**
- **Write specs up front in SeamSpec too.** Rejected: it competes on the spec-first tools' ground and adds a second source of truth next to the ledger.
- **Commit a generated spec file from `init`.** Rejected: it would be the notes file ADR-20261007-ac04 decided against. A team can still write one on purpose and check it in CI.
- **Rename the product.** Not now: the generated spec makes the name true, and the names are already claimed. Revisit only if the positioning still confuses people after the README.

## Enforced Invariants

To be proposed when built: "the generated spec lists only human-approved rules", and "the generated spec is built from the ledger alone".

## Consequences

* SPEC §15 gains `seamspec spec` (§15.2 describes the plan until it's built); §22 changes: `seamspec spec` and the positioning join week 5, the OpenSpec importer moves from "Later" to v0.2.
* The area rule moves from the Claude adapter to a shared module when `seamspec spec` is built.
* `docs/PROGRESS.md` records the order and the dogfooding findings.
