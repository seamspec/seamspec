---
name: checkpoint
description: End-of-session SeamSpec check. Verifies the locked rules, proposes rules for behavior built this session, and records approaches that failed. Use when the user says "wrap up", "checkpoint" or "before I commit".
argument-hint: "[area to focus on]"
---
Run a SeamSpec checkpoint for this session. Optional focus: {{args}}

1. Call `verify(scope="all")`. If it reports `not_permitted`, run `seamspec verify` with your
   shell tool instead (the user may be asked to allow it). If any LOCKED rule fails, stop here:
   fix the regression, or, if the change is intentional, follow the supersede steps
   (`/seamspec:supersede`).
2. List the files changed this session: `git diff --name-only HEAD`, plus untracked files.
3. Call `get_constraints` on them, so you don't propose a rule that already exists.
4. If the project keeps a list of rules it intends to lock (for example a section of its
   plan), start with the ones whose code now exists and works. Then pick behaviors
   established this session that are worth protecting. At most 3 in total (fewer is fine;
   if `.seamspec/config.toml` sets `commands.max_proposals_per_run`, use that limit): explicit
   user constraints, user-visible behavior, security, data integrity. Skip cosmetic or trivial
   behavior. Propose each with `propose_invariant`, then run `seamspec verify --proposed <id>`.
5. Record every approach tried and abandoned this session with `log_dead_end`.
