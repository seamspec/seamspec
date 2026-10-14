---
name: drain
description: Sort the user's BRAINDUMP.md notes into proposed rules, decisions, dead ends or dismissals. Use when the user says "sort my braindump", "drain", or says yes when SeamSpec reports new notes.
argument-hint: "[note ids]"
---
Sort the notes in the user's BRAINDUMP.md. Only these notes, if given: {{args}}

1. Call `braindump_pending()` (or run `seamspec drain --json`). If nothing is pending, say so and stop.
   If SeamSpec's tools are missing or fail, use its commands instead: `seamspec propose`,
   `seamspec propose-decision`, `seamspec dead-end`, each reading the tool's fields as JSON on stdin.
   Never search outside this project for SeamSpec's settings.
2. Classify each note as exactly one of:
   - **constraint**: a behavior the code must keep ("X must never…", "always…");
   - **decision**: a choice of approach or convention, not a single testable behavior;
   - **failed_approach**: something tried that didn't work, and why;
   - **exploration**: an idea or question to look into;
   - **task**: something to do.
   If unsure between constraint and exploration, choose exploration.
3. **constraint:** if the code it governs exists and works, write a focused behavior-level test and
   call `propose_invariant` with `origin_type="braindump"`, `origin_ref=<note id>` and
   `origin_text=<the note>`; then run `seamspec verify --proposed <id>`. If the code doesn't exist
   yet, leave the note pending and say so.
4. **decision:** `propose_decision` with `origin_ref=<note id>`. If part of it is testable now, also
   propose that part as a rule.
5. **failed_approach:** `log_dead_end` with `origin_ref=<note id>`.
6. **exploration** and **task:** dismiss them all in one call:
   `braindump_pending(dismiss={"<note id>": "exploration", "<note id>": "todo"})`, or without the tools
   `seamspec drain --dismiss <note id>=exploration --dismiss <note id>=todo`. They stay in the file.
7. Propose at most 3 rules in one sort (or `commands.max_proposals_per_run` from
   `.seamspec/config.toml`); leave the rest pending and say so.
8. Never edit BRAINDUMP.md: the notes are the user's. `seamspec drain --tidy` is theirs to run.
9. Tell the user what each note became. Rules and decisions wait for them in `seamspec review`;
   offer an explanation from SeamSpec's reviewer (`/seamspec:explain`) first.
