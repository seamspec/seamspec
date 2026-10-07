---
name: context
description: Explain which SeamSpec rules, dead ends and decisions apply to some files, in plain language. Use when the user asks "what applies here?", "what are the rules for this file?" or before a big change.
argument-hint: "[files...]"
---
Show the SeamSpec constraints for: {{args}}

1. If no files were given, use the files discussed in this conversation, else
   `git diff --name-only HEAD`.
2. Call `get_constraints(files)`.
3. Explain in plain language:
   - LOCKED rules: must keep holding;
   - PROPOSED rules: waiting for the human's review;
   - dead ends: approaches that failed before, and why;
   - linked decisions (ADRs).
4. Flag anything that conflicts with the current plan, and say what you would do about it.
