---
name: lock
description: Protect a behavior you just built as a proposed SeamSpec invariant (a plain-language rule plus a test). Use when the user says "lock this", "protect this" or "make that a rule".
argument-hint: <behavior to protect>
---
Protect this behavior as a SeamSpec invariant: {{args}}

1. Identify the files that implement it. Call `get_constraints` on them. If the new rule
   conflicts with a LOCKED invariant, stop and explain the conflict instead of proposing.
2. Write ONE focused, behavior-level test: inputs → outputs, or a property over a range.
   Do not test private helpers or internal structure. Use the runner, test location and
   import style that `get_constraints` returns under `runners`.
3. Call `propose_invariant` with:
   - a precise one-sentence `assertion`
   - the narrowest `scope_paths` globs that cover the behavior
   - `origin_text` = the user's original request for this behavior, quoted
   - `adr` (`context`, `decision`, `consequences`) if a design choice was made
4. `propose_invariant` does not run the test. Run it with your shell tool:
   `seamspec verify --proposed <id>` (the user may be asked to allow this).
5. If the test fails: fix the test only if the test is wrong; if the code is wrong, report
   the bug and do not keep the proposal. Retry a fixed test with `replace_id`, then run it again.
6. Tell the user the rule is only proposed: it is locked when they approve it in `seamspec review`.
