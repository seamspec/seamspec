---
id: ADR-20261006-0f6e
title: Dogfooding - SeamSpec governs its own repo; docs/adr stays until agents have an ADR tool
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-06
scopes: [".seamspec/**", "docs/adr/**", "seamspec/core/lifecycle.py", "seamspec/core/root.py", "seamspec/cli.py", "seamspec/templates/commands/_footer.md"]
invariants: ["inv_4b4f5ea7", "inv_aef791d8", "inv_e65a013c", "inv_7fd1e45d", "inv_22e94e77", "inv_486142b7"]
supersedes: null
superseded_by: null
---

# ADR-20261006-0f6e: Dogfooding - SeamSpec governs its own repo; docs/adr stays until agents have an ADR tool

## Context
ADR-20261005-ae6e decision 5 planned that, from week 3, SeamSpec governs its own repo and `docs/adr/` moves to `.seamspec/adrs/`. After the setup-friction work (#19, #20) the owner set it up:

- `seamspec init` in **enforced** mode, with the consent screen answered by the owner at a terminal;
- the plugin installed at local scope, with the owner's OK;
- six candidate rules proposed by the agent and approved by the owner in `seamspec review`.

## Decision

1. **SeamSpec governs this repository in enforced mode.**
   - Six LOCKED rules, each protecting a promise already made in the spec or an ADR:

     | Rule | Protects |
     |---|---|
     | `inv_4b4f5ea7` | Test runs get no "under verification" signal (§12.4.7) |
     | `inv_aef791d8` | A scripted `init` never trusts a clone (ADR-20261005-9b8f) |
     | `inv_e65a013c` | The Stop check finishes before the hook timeout (ADR-20261005-5675) |
     | `inv_7fd1e45d` | MCP never runs unapproved tests (§12.4.3) |
     | `inv_22e94e77` | Wrappers never run a `seamspec` from the current folder |
     | `inv_486142b7` | `init` never changes Claude Code settings silently (ADR-20261005-428a) |

   - The git pre-commit hook runs them on every commit. The first commit (`f147659`) passed through it.
2. **`docs/adr/` stays where it is for now**, amending ADR-20261005-ae6e decision 5.
   - In enforced mode, ledger protection denies agent edits to `.seamspec/**`.
   - The only SeamSpec way to write an ADR in v0.1 is attached to a rule proposal, and most of this repo's ADRs are process decisions with no rule.
   - Moving them would force the agent to write ADRs through the shell, the exact bypass SeamSpec warns about.
   - They move once an agent-facing ADR tool exists (`propose_decision`, §14, v0.2).
3. **Fixes for what dogfooding found**, in this PR:

   | # | Finding | Fix |
   |---|---|---|
   | 2 | The plugin prompt said it changes "only" `.claude/settings.local.json`; Claude Code also records the install under `~/.claude/plugins/` | Prompt and SPEC §16.1 now say both |
   | 3 | The agent ran `seamspec verify --proposed A B C`; the flag is repeatable, but SPEC wrote `--proposed <id...>` and the skills said `<ids>` | SPEC §15 and the skill footer show `--proposed <id>`, repeated per id |
   | 4 | `seamspec review` run from the parent folder said only "No .seamspec/config.toml found" | The message names the folder it searched from and says to run SeamSpec inside the repository |
   | 5 | `approved_by` was the OS login `vamship`: with no `git config user.name`, git falls back to the OS full name, but SeamSpec read only `git config` and dropped the email | `approver_identity()` asks git for the identity it records (`git var GIT_AUTHOR_IDENT`); SPEC §11.1 updated. The six existing records keep `vamship`, because the agent doesn't edit approved records |

**Noted, not changed here:**
- The six rules' origin text says "2026-10-07"; the correct date is 2026-10-06. It's the agent's mistake, inside owner-approved records, so it's left to the owner.
- The owner's demo repo earlier failed with "Runner executable 'pytest' not found". The project-tool lookup from #19 should cover it if the demo has a `.venv`; to be rechecked.

**Alternatives considered:**
- *Exclude `.seamspec/adrs/` from ledger protection:* rejected. ADRs are part of the ledger, and a carve-out weakens the rule for every user.
- *Move the ADRs and have the agent write them through the shell:* rejected (decision 2).

## Enforced Invariants
The six rules in decision 1.

## Consequences
* Every change to SeamSpec now passes its own pre-commit check. The plugin gives new sessions in this repo edit-time context and the Stop check.
* `docs/adr/` remains the home of build decisions until v0.2.
* SPEC §11.1, §15 and §16.1 are updated in the same PR.
