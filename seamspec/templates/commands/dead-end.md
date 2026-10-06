---
name: dead-end
description: Record an approach that was tried and failed, so SeamSpec reminds future sessions not to retry it. Use when the user says "that didn't work" or "don't try that again".
argument-hint: "[what failed]"
---
Record a failed approach as a SeamSpec dead end. User note (may be empty): {{args}}

1. Use the user's note, or identify the most recent approach in this conversation that was
   tried and abandoned. Only log approaches that were actually tried, not speculative worries.
2. Write `approach` as one specific sentence (library, pattern, config, algorithm).
3. Write `failure_symptom` as the observed evidence: error message, failing test, measured
   number, or incorrect behavior.
4. Choose the narrowest `scope_paths`. If it relates to an existing invariant (check with
   `get_constraints`), set `related_invariant`.
5. Call `log_dead_end`.
