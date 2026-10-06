---
id: ADR-20261005-5675
title: Claude Code plugin, verified in real sessions
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-05
scopes: ["seamspec-plugin/**", "seamspec/core/commands.py", "seamspec/templates/commands/**"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261005-5675: Claude Code plugin, verified in real sessions

## Context
Week 3's third slice packages the hooks (#16) and the MCP server (#17) as a Claude Code plugin with the `/seamspec:lock` and `/seamspec:dead-end` skills (SPEC §15A, §16.1). The spec asked for the plugin format to be checked against current docs and for a hands-on check that edit-time context reaches the model. The owner approved up to five short real sessions on their account.

## Decision

1. **Layout:** `seamspec-plugin/` in this repo, with `.claude-plugin/plugin.json` (`name: "seamspec"`), `hooks/hooks.json`, `.mcp.json`, `skills/<name>/SKILL.md` and `scripts/`. `claude plugin validate` passes, and a test runs it when the CLI is available.
2. **Wrappers go in `scripts/`, not `bin/`.** Per the plugin reference, a plugin's `bin/` is added to the agent's Bash `PATH`, and plugins containing `bin/` aren't installed on claude.ai or Cowork.
3. **The MCP server gets `SEAMSPEC_ROOT=${CLAUDE_PROJECT_DIR}`,** so it resolves the project even though plugin MCP servers don't receive `CLAUDE_PROJECT_DIR` in their environment.
4. **Skills are generated from `seamspec/templates/commands/`** by `python -m seamspec.core.commands`; a test fails if the committed `SKILL.md` drifts from its template. The skill text tells the agent to use the runner hints from `get_constraints` (no `{{runners}}` placeholder: the plugin is project-independent).
5. **Until release, try it with `claude --plugin-dir <repo>/seamspec-plugin`.** Marketplace install and an `init` hint come with weeks 4–6 (publishing stays gated, ADR-20261005-3adc).

## Hands-on results (claude 2.1.278, Haiku 4.5, `claude -p`, throwaway repo with one LOCKED rule "retry delay never exceeds 30 seconds")

| Session | Prompt | Observed | Cost |
|---|---|---|---|
| 1 | "Raise the retry cap from 30 to 60 seconds" | Plugin loaded; MCP server `plugin:seamspec:seamspec` connected with all 5 tools; skills registered. The agent edited, then said *"I see there's a LOCKED invariant… 'Retry delay never exceeds 30 seconds'"* **before any Stop feedback** (its `get_constraints` call was denied, so the PreToolUse context was its only source). The **Stop gate blocked 3 times** naming `inv_a763e70d` (`assert 60.0 <= 30`); the agent tried `request_supersede` (not permitted in this headless run), then **reverted** its change, and the final check passed. | $0.08 |
| 2 | `/seamspec:lock jitter returns half of the given delay` | `get_constraints` → `propose_invariant` (test, one-sentence rule, origin quoted) → `seamspec verify --proposed` passed → summary block with "Next: run `seamspec review`". Ledger: 1 proposed, 1 locked; the agent approved nothing. | $0.05 |
| 3 | `/seamspec:dead-end` + a failed approach | `log_dead_end` with approach, evidence and the narrowest scope; `seamspec context` shows it as history. | $0.04 |

Findings:
- **Edit-time context arrives with the first edit, not before it.** The model learns the rule as it makes that edit and reacted immediately in session 1. Teams that want the rule shown strictly before any change can use `gate_mode = "deny_once"`.
- **Claude Code labels a blocking Stop hook as "Stop hook error"** in its notifications, although the hook exits 0 with valid JSON. That's cosmetic, and the docs should mention it so users aren't alarmed.
- **Headless runs need the MCP tools allowed** (`--allowedTools mcp__plugin_seamspec_seamspec__…`); interactive sessions ask the user. This matters for the benchmark.

**Alternatives considered:**
- *Wrappers in `bin/`:* rejected (decision 2).
- *Keep the PostToolUse fallback:* not needed; PreToolUse context works (ADR-20261005-5009).

## Enforced Invariants
None yet. Week 3 dogfooding candidates: "committed skills match their templates", "the hook wrapper is silent when the CLI is missing".

## Consequences
* Week 3's exit criterion "core loop works end to end in Claude Code" is met on a sample repo.
* The benchmark harness can drive sessions the same way (`claude -p --plugin-dir … --allowedTools …`).
* SPEC §14.3, §16.1, §21 and §26 (still-open #3, now resolved) are updated in the same PR.
