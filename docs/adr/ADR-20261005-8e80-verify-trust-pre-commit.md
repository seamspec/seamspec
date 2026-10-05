---
id: ADR-20261005-8e80
title: verify CLI, consent and trust, pre-commit gate
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-05
scopes: ["seamspec/core/trust.py", "seamspec/core/tree.py", "seamspec/installers/**", "seamspec/cli.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261005-8e80: verify CLI, consent and trust, pre-commit gate

## Context
Week 2's third slice adds the auto-run consent screen, repo trust (`seamspec trust`), the `seamspec verify` command and the git pre-commit gate (SPEC §12.4.5, §12.4.6, §15, §16.4). Its tests drive the real CLI, real `git commit` and the installed hook in Python and TypeScript repos. The spec left a few behaviors open, and one test exposed a real bug.

## Decision

1. **`verify` exits 1 whenever anything fails, in every mode,** so an agent running `verify --proposed` through its shell notices a failure. `--gate` adds what pre-commit needs: no prompts, auto-run consent required, the journal check, and the pending-review reminder.
2. **`verify --ci` skips trust, consent *and* the journal check.** CI clones have no local journal, so every approval in the PR would look unjournaled. In CI, status changes are covered by `doctor --ci` (forward-only checks + retirement summary, week 4).
3. **Untrusted clone:** an interactive `verify` offers `seamspec trust` first; a non-interactive one (agent shell, hook) fails with "Run `seamspec trust`" and runs nothing.
4. **Consent at `init`:** with no terminal and no `--accept-auto-run`, the answer is No (advisory mode), with a note on how to turn runs on. **Bug fixed:** re-running `init` with consent after an earlier No left the config in advisory mode, so the advice in the note did nothing. Now `init` rewrites the `mode` line, and for `strict` restores the strict values of the lines `init` itself wrote.
5. **`init` trusts the clone when it creates `config.toml`** (the person running it just wrote those runner commands). An existing config, e.g. in a fresh clone, is not trusted automatically.
6. **`trust_level = "harness"` moves from v0.2 into v0.1.** `strict` already defaults to it (§26 #8), so without it the default would quietly do nothing. It's small: the trust hash also covers every LOCKED test's hash.
7. **Pre-commit hook:** installed only with consent, into the hooks directory git reports (honoring `core.hooksPath` and worktrees). It never overwrites a foreign hook, and defers to pre-commit / Husky / Lefthook by printing the line to add. The script fails loudly if `seamspec` isn't installed, and `cd`s into the SeamSpec root when that is a subfolder of the git repo.

**Alternatives considered:**
- *`verify` exits 0 unless `--gate`:* rejected; an agent could miss a failing proposed test.
- *Run the journal check in CI too:* rejected; it would flag every legitimate approval in a PR.
- *Silently keep advisory mode when consent comes later:* rejected; it contradicts the message telling users to re-run `init`.

## Enforced Invariants
None yet. Week 3 candidates: "pre-commit blocks a regression and names the rule", "an untrusted clone runs nothing", "re-running init with consent leaves advisory mode".

## Consequences
* Issue #2's exit criteria are covered by automated tests: propose → approve → pre-commit blocks a regression, naming the rule, in Python and TypeScript; an empty or all-skipped harness fails; an untrusted clone runs nothing.
* SPEC §7.3, §9.5, §12.4.5, §15, §16.4, §19.8a, §21, §22 and §26 #8 are updated in the same PR.
* What's left in Week 2: the `review` TUI with the red-green check.
