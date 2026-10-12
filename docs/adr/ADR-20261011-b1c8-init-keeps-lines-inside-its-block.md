---
id: ADR-20261011-b1c8
title: "`seamspec init` keeps lines someone else wrote inside its CLAUDE.md block"
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-11
scopes: ["seamspec/installers/directive.py", "seamspec/templates/directive_known_lines.txt", "seamspec/installers/scaffold.py", "seamspec/cli.py", "seamspec/core/doctor.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261011-b1c8: `seamspec init` keeps lines someone else wrote inside its CLAUDE.md block

## Context

Dogfooding finding #8 (2026-10-11). `seamspec init` owns the text between two markers in `CLAUDE.md` and replaces all of it on every run (ADR-20261005-c41d). The begin marker says "edit outside these markers".

In the owner's project an agent was told "this is a solo project, commit directly to `main`" and wrote that instruction into `CLAUDE.md` on the line right after the begin marker, inside the block. Nobody noticed. The next `seamspec init` (needed to pick up the new block wording) would have deleted the owner's instruction without a word. The owner asked whether rerunning `init` was safe, and the honest answer was "move that line by hand first".

A marker comment doesn't stop an agent, or a person in a hurry, from typing in the wrong place. A tool that says it "never clobbers" must not delete an instruction because of where it was typed.

## Decision

1. **Before replacing its block, `init` keeps every line in it that SeamSpec never shipped.** Those lines are moved to just above the block, in their original order, with a blank line before the block. Blank lines are not kept. Everything outside the markers is untouched, as before.
2. **SeamSpec recognises its own lines, old and new.** `seamspec/templates/directive_known_lines.txt` lists every line the block has ever contained (29 lines across the 6 versions so far), each as the first 16 hex characters of the SHA-256 of the line without surrounding whitespace. The current template's lines always count as known. So upgrading from older wording moves nothing.
3. **The list only grows.** After editing `directive.md`, `uv run python -m seamspec.installers.directive` appends the new lines; a test fails if the file doesn't cover the current template. Without this, the *next* wording change would mistake today's lines for someone else's.
4. **`init` says what it kept**, and shows each line:

   ```
     updated   CLAUDE.md
     CLAUDE.md: 1 line inside SeamSpec's block was not SeamSpec's. Kept, and moved above the block:
       | This is a solo project: commit directly to `main`; don't create feature branches.
   ```

5. **`doctor` says it is safe.** When the block contains such lines, its drift warning reads "N line(s) inside the SeamSpec block in CLAUDE.md … not written by SeamSpec: rerun `seamspec init`, which keeps them (moved above the block) and updates the block".

**What this does not do:**
- **It can't tell an edit of SeamSpec's own line from a new line.** If someone changes the wording of rule 6 inside the block, the changed line is "not SeamSpec's": `init` restores rule 6 in the block and keeps the changed line above it, where the output shows it. That is deliberate. Outside the block the file is the user's, so the same text could have been written there anyway; and showing a kept line is better than guessing which edits were unwanted.
- **It keeps lines, not layout.** A kept paragraph loses its blank lines; a line that only made sense between two SeamSpec lines now sits above the block.

**Alternatives considered:**
- **Tell the user to move the line first** (the status quo, plus a warning). The owner asked for exactly this not to be needed, and a warning is easy to miss in a scripted `init`.
- **Refuse to run while the block has foreign lines.** Safe, but `init` is also how the mode, the plugin and the hook are set up; blocking all of that on a stray line is out of proportion.
- **Leave foreign lines inside the block.** The block would then never match the template, `doctor` would warn for ever, and the next agent would have an example of writing inside it.
- **Compare with the current template only.** Then every upgrade would "rescue" SeamSpec's own previous wording and stack it above the block.
- **Store the known lines as plain text.** Old wording, including rules that were later reworded or dropped, would then be searchable in the package as if it still applied. Hashes say "SeamSpec wrote this once" and nothing else.
- **A fuzzy match, to drop edits of SeamSpec's lines.** It would decide silently which of the user's lines to delete, which is the failure this record removes.

## Enforced Invariants

To be proposed: "re-running `init` never removes a line it didn't write from `CLAUDE.md`".

## Consequences

- Rerunning `seamspec init` is safe whatever was typed inside the block. In the owner's project the "solo project" line moves above the block on the next run, with no manual step.
- One more generated file to keep current (`directive_known_lines.txt`), guarded by a test, like the plugin skills and the config schema.
- A deliberately tampered line (for example "agents approve invariants") is no longer erased by `init`; it is moved out of the block and shown. It had no force inside the block either: the hooks, pre-commit and CI enforce the rules, not this text (SPEC §18).
- `InitReport` gains `kept_lines`.
