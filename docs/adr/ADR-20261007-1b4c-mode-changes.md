---
id: ADR-20261007-1b4c
title: Changing the mode after init - keep by default, raise with consent, lower only by a human
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-07
scopes: ["seamspec/installers/scaffold.py", "seamspec/installers/git_hooks.py", "seamspec/cli.py", "seamspec/core/doctor.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261007-1b4c: Changing the mode after init - keep by default, raise with consent, lower only by a human

## Context
Week 4 (issue #4) lists "`--mode advisory|enforced|strict` handling" (§7.3). An audit found:

1. **Only advisory → enforced/strict worked** after `init`. Enforced ↔ strict and anything → advisory didn't. And `--mode` defaulted to `enforced`, so a naive fix would let a plain re-run of `init` quietly turn a strict repo into an enforced one.
2. **Lowering the mode switches checks off.** `init` needs no terminal, so an agent could run `seamspec init --mode advisory` in its shell to silence the Stop gate.
3. **In advisory mode a pre-commit hook left from earlier still ran tests,** although §7.3 says advisory never runs tests automatically.
4. **`doctor` didn't check strict mode's CI workflow and CODEOWNERS.**
5. **A mode change in a PR was invisible to reviewers.**

## Decision
1. **`--mode` defaults to "keep".** Enforced and strict stay as they are. A new or advisory setup is offered enforced, so "re-run `init` with consent to turn runs on" still works (ADR-20261005-8e80).
2. **Raising the mode needs automatic runs allowed on this machine.** Without consent, the config is kept and `init` says why.
3. **Lowering the mode is a human decision,** like approving a rule. The CLI requires an interactive terminal (`require_interactive`, with the same test override) and asks *"Lower the mode from … to …?"*. An agent's shell is refused with an explanation. CI is unaffected: `verify --all --ci` doesn't look at the mode.
4. **Minimal rewrites.** Only the `mode` line changes, plus, when entering or leaving strict, the `fail_closed` / `trust_level` lines `init` itself wrote. Values a human edited stay. strict → enforced restores the file byte for byte.
5. **Advisory runs nothing automatically.** Switching to advisory removes SeamSpec's own pre-commit hook (never anyone else's), and `verify --gate` exits 0 in advisory mode with a note. `doctor` warns about a leftover SeamSpec hook.
6. **Strict mode's extras are checked.** `doctor` warns when strict mode lacks the CI workflow or the CODEOWNERS block, or the block still names `@your-team/leads`.
7. **Reviewers see mode changes.** `doctor --ci` puts "Mode changed: X → Y" at the top of the retirement summary.

**Alternatives considered:**
- *A separate `seamspec mode` command:* not needed. `init` already owns consent, hooks, CI and CODEOWNERS, which a mode change touches.
- *Fail CI when the mode is lowered:* rejected. Lowering can be legitimate; the summary makes it visible, and PR review (CODEOWNERS in strict) decides.
- *Leave the hook in place in advisory mode:* rejected. It contradicts §7.3, and it surprised users with blocked commits.

## Corrections from the code review of #36 (fixed in #37)
1. **Lowering strict → enforced is a lowering, not a raise.** It no longer needs auto-run consent; `scaffold.init` compares `MODE_RANK`. Before the fix, declining the consent screen silently kept the repo strict.
2. **The consent screen is only shown when raising the mode or setting up.** Lowering, or choosing advisory, no longer asks for consent or records it, so this machine's earlier answer is never overwritten with a "no" nobody gave (the dogfooding finding #7 pattern).
3. **After declining consent on an enforced or strict repo,** `init` now says runs are off *on this machine* and names the repository's real mode, instead of "(advisory mode)".
4. **Decision 3's "an agent's shell is refused" overstated it.** The terminal requirement is a speed bump, as for approving: an agent with an unrestricted shell can edit `config.toml`, call `scaffold.init` from Python, or set the test override. The backstop is decision 7, the mode change at the top of the CI summary, plus PR review. SPEC §7.3 now says so.

## Enforced Invariants
None yet. Dogfooding candidate: "an agent's shell can't lower the mode".

## Consequences
* Week 4's mode-handling item is done. SPEC §7.3, §12.4.5, §16.4, §19.6a and §19.11a are updated in the same PR.
