---
id: ADR-20261007-8663
title: The remaining v0.1 skills - supersede, checkpoint, context, status
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-07
scopes: ["seamspec/templates/commands/**", "seamspec-plugin/skills/**", "seamspec/core/commands.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261007-8663: The remaining v0.1 skills - supersede, checkpoint, context, status

## Context
Week 4 (issue #4) adds the four remaining workflow commands from SPEC §15A.2 as Claude Code plugin skills, next to `lock` and `dead-end` (ADR-20261005-5675). SPEC §15A.3 has draft templates. Since they were written, v0.1 has settled some details:
- the plugin is the same for every project;
- MCP `verify` refuses when automatic runs aren't permitted;
- `seamspec status` has no host tiers yet;
- the benchmark showed agents rely on `request_supersede`, and stop before committing a rule-breaking change.

## Decision
1. **Four new skills,** generated from `seamspec/templates/commands/` like the first two:
   - `/seamspec:supersede <invariant_id> <reason>`;
   - `/seamspec:checkpoint [focus]`;
   - `/seamspec:context [files...]`;
   - `/seamspec:status` (no argument).
2. **Differences from the §15A.3 drafts:**
   - **No `{{max_proposals}}` or `{{runners}}` in v0.1.** The plugin can't know a project's values. `checkpoint` says "at most 3, or `commands.max_proposals_per_run` if set in `.seamspec/config.toml`", and runners come from `get_constraints`. Per-project rendering arrives with the v0.2 hosts.
   - **`checkpoint` falls back to `seamspec verify` in the shell** when MCP `verify` reports `not_permitted` (advisory mode, or no consent or trust). It also runs `seamspec verify --proposed` after each proposal.
   - **`supersede` also runs the replacement's test,** handles a missing invariant id by finding the rule and confirming it with the user, and says plainly not to commit code that breaks the old rule until the human approves. This matches what agents did in the benchmark (ADR-20261006-b270).
   - **`status` leaves out host tiers,** which v0.1 doesn't report, and ends with the one command the user should run next.
3. **Descriptions carry trigger phrases** ("wrap up", "what applies here?", "the rule has changed"…), so Claude can pick a skill from plain language, as the directive's rule 8 already promises.
4. **Context cost:** about 458 tokens are always loaded for the six skill descriptions (measured with `claude plugin details`), up from about 94 with two. Each skill costs 500–920 tokens only when it runs. This is accepted for v0.1; the descriptions can be trimmed if the benchmark's cost overhead needs it (ADR-20261006-b270, decision 4).

**Alternatives considered:**
- *Render the plugin skills per project at `init` time to fill in `{{max_proposals}}`:* rejected for v0.1. Plugin files live in the plugin, not in the project, and copying skills into each repo would bring back the un-namespaced `/lock` problem (§15A.4 note).

## Enforced Invariants
None yet. Dogfooding candidate: "committed plugin skills match their templates" (already a test).

## Consequences
* Week 4's skills deliverable is done. SPEC §15A.3 now mirrors all six templates exactly, and §19.8c is updated.
