# SeamSpec Protocol

This repository uses SeamSpec. Locked invariants are enforced by hooks, pre-commit, and CI —
failing them will block you from finishing and block commits.

1. Before editing a file, call `get_constraints(files)` (or run `seamspec context <files>`).
   Respect every LOCKED invariant. Approaches listed as previously failed (dead ends) failed for
   the stated reason; don't reuse them unless that reason no longer applies.
2. When you establish a new behavior worth protecting, call `propose_invariant` with a focused,
   behavior-level test (not implementation details). The tool does not run the test: run
   `seamspec verify --proposed <id>` with your shell tool and fix the test until it passes.
3. When an approach fails, call `log_dead_end` with what you tried and why it failed.
4. If your change must intentionally break a LOCKED invariant, do not edit or delete its test.
   Call `request_supersede(invariant_id, reason, replacement_id)` and tell the user.
5. Never edit files under `.seamspec/` directly; use SeamSpec tools.
6. Only humans approve invariants. Remind the user to run `seamspec review` when proposals are pending.
7. When the user runs a `/seamspec:*` workflow command, follow its steps exactly and end with
   the SeamSpec summary block.
8. Users don't have to type commands. Treat plain requests as the matching workflow command:
   "protect this" / "lock that" → lock; "that didn't work" → dead-end;
   a changed requirement for a LOCKED rule → supersede; "what applies here?" → context;
   "wrap up" → checkpoint.
