---
id: ADR-20261005-6f2a
title: Week 1 implementation decisions (schemas, config strictness, store, context, spec listings)
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-05
scopes: ["seamspec/core/**", "seamspec/installers/**", "seamspec/schemas/**", "docs/SPEC.md"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261005-6f2a: Week 1 implementation decisions

## Context
Week 1 implemented the core ledger (`root`, `config`, `models`, `store`, `scope`, `hashing`, `context`), the JSON Schemas and `seamspec init` / `status` / `context` from SPEC §19. Writing and testing the code exposed places where the reference listings were wrong or underspecified.

## Decision

1. **Schema status rules require non-null values (§10.1, §10.2).** The spec's `allOf` used `required` alone, but every record carries every key, so a `LOCKED` record with `approved_by: null` passed. The `then` branches now also require the fields to be strings. Dead ends gain the matching rule: `RETIRED` needs `retired_reason`. The Pydantic models enforce the same rules, and tests check that bad records fail **both** validators.
2. **Unknown config keys are errors (§19.2).** Every config table uses `extra="forbid"`, so a typo fails loudly. `runners` defaults to `{}` (for repos with no detected language), `braindump.nudge` is added to the model to match §9.5, runner `filename` must contain `{id}`, and `config_files` must stay inside the repo.
3. **Models are strict (§19.3).** `extra="forbid"`, the schemas' patterns and limits, and timezone-aware datetimes only.
4. **Store (§19.4).** `create()` refuses to overwrite and `save()` replaces. Ids are validated before any path is built, which closes a path-traversal hole in `get("inv_../../x")`. Load errors raise `RecordError` naming the bad file.
5. **Scope matching uses `pathspec.GitIgnoreSpec` (§19.5).** pathspec 1.x deprecates `gitwildmatch`.
6. **`ConstraintSet.render()` returns the body only (§19.6).** The hook in §19.10 added its own header, so the old listing doubled it. Dead ends render as history per §11.3, and truncation reports `omitted`. Directive rule 1 (§18) is reworded to match: don't reuse a failed approach *unless the reason no longer applies*.
7. **`config.json` is generated from the config model** (`config_json_schema()`), and a test fails if the packaged file is stale. `invariant.json` and `dead_end.json` stay hand-written.
8. **Implemented modules are the source of truth.** In §19, a module's full listing is replaced by a short contract plus a link to the code once it's implemented; unbuilt modules keep their listing. This keeps "spec and code agree" (ADR-20261005-ae6e) achievable without maintaining two copies.
9. **Tooling.** uv with a flat layout (`module-root = ""`, matching §21), ruff (line length 120; `docs/` and `notes/` excluded, so SPEC code blocks are never reformatted), pytest, and a GitHub Actions workflow running on Python 3.11–3.14 (plus macOS). `rfc3339-validator` is a dependency so `date-time` formats are actually checked.

**Alternatives considered:**
- *Keep full listings in §19 and sync them by hand:* rejected. They had already drifted (doubled header, broken schema rule) before any code existed.
- *Ignore unknown config keys (Pydantic default):* rejected. A silently ignored `fail_closed = true` typo would weaken enforcement without anyone noticing.
- *src layout:* rejected for now to match §21. Revisit if import confusion appears.

## Enforced Invariants
None yet. From week 3, when SeamSpec governs its own repo, candidates include: "a LOCKED record with null approval fields fails schema validation" and "`init` never changes content outside the CLAUDE.md markers".

## Consequences
* SPEC §9.4, §10.1, §10.2, §18, §19.1–§19.6a and §21 are updated in the same commit.
* Existing hand-written records with unknown keys or naive timestamps will fail to load. There are none yet.
* Future `doctor` work builds on `core/schemas.validation_errors()` and `installers/directive.drift()`.
