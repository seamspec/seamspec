---
id: ADR-20261005-c076
title: The agent requests a Copilot review on every PR it opens
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-05
scopes: ["CLAUDE.md", ".github/**", "docs/**"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261005-c076: The agent requests a Copilot review on every PR it opens

## Context
ADR-20261005-d8bc point 5 assumed "Copilot reviews automatically". It doesn't: automatic review requests need a branch ruleset, and rulesets aren't enforced on a private repo in a free organization (GitHub Team is required). Across PRs #8–#14, Copilot reviewed only when someone requested it by hand. Its one review so far (#8) found a real bug, so the review is worth having.

## Decision
This amends ADR-20261005-d8bc point 5.

1. **Right after opening a PR, the agent requests Copilot's review:** `gh pr edit <n> --add-reviewer @copilot`.
2. **Before asking the owner to merge, the agent reads the review** and, for each finding:
   - fixes it on the same branch and replies in the thread with what changed, or
   - replies explaining why no change is needed.

   The PR summary says which.
3. If Copilot's review hasn't arrived after a reasonable wait (or GitHub is having trouble), the agent says so in the PR and the owner decides whether to merge without it.
4. CI green remains a requirement; Copilot's review stays advisory. The owner still merges.
5. When the repo goes public, the ruleset from ADR-20261005-d8bc point 7 takes over automatic requests, and step 1 becomes a fallback.

**Alternatives considered:**
- *Upgrade to GitHub Team for automatic requests:* deferred, as in ADR-20261005-d8bc.
- *Skip Copilot review:* rejected; it caught a real bug on its only run.

## Enforced Invariants
None (process decision).

## Consequences
* Every PR gets a Copilot review **requested** without a paid plan, and normally receives it before merge. The exception is decision 3: if no review arrives, the owner may merge without one. Each review costs a few minutes of waiting.
* `CLAUDE.md` and the PR template list the step, so any agent picking up the work follows it.
