---
id: ADR-20261027-9d14
title: The notes file stays inside the repository, every committed field is redacted, and plugin scope is checked
status: ACCEPTED
date: 2026-10-27
scopes: ["seamspec/core/braindump.py", "seamspec/core/config.py", "seamspec/core/lifecycle.py", "seamspec/installers/claude_plugin.py", "seamspec/installers/scaffold.py", "seamspec/cli.py", "seamspec/mcp_server.py", "docs/SPEC.md"]
invariants: []
supersedes: null
superseded_by: null
---

# The notes file stays inside the repository, every committed field is redacted, and plugin scope is checked

## Context

The catch-up review of #53 to #95 (draft #97, 2026-10-26) found six problems in BRAINDUMP and the plugin install, all checked against the code:

1. **`braindump.path` could point anywhere.** A cloned repository's `.seamspec/config.toml` (or a committed `BRAINDUMP.md` link) could make `drain --json` and `braindump_pending` read a file outside the project out to the agent, `init` create one, and `drain --tidy` rewrite one.
2. **Only the origin text was redacted.** `propose_decision` wrote `title`, `context`, `decision` and `consequences` as given, and `propose_invariant` its `title`, `assertion` and draft ADR. A key the agent repeated there reached a committed record, although `braindump.redact_secrets` is on.
3. **`context --json` left out planned rules,** which the text output and MCP `get_constraints` show.
4. **A fence was cut to three characters,** so a ```` ``` ```` line inside a ```` ```` ```` block closed it. The rest of the block became separate notes, with different ids.
5. **Tidy removed the first lines matching the note,** wherever they were: in a code example, or at the start of a longer note written earlier. The sorted note stayed, and the other text lost a line.
6. **`init --plugin-scope project` reported "already enabled"** when only this user had the plugin on (local or user scope), so the team's committed settings were never written.

## Decision

1. **The notes file must be inside the repository.** `braindump.path` gets the same check as the runner paths: relative, no `..`. The check now also refuses Windows-rooted (`\x`) and drive-relative (`C:x`) paths, for every path it covers. At run time `braindump.location(root, path)` follows links and returns `None` when the file is outside the project. `read()` then sees no file, `tidy()` writes nothing, `init` reports it as skipped, and `drain` and `braindump_pending` say why. A link inside the project is followed, and tidy writes where it points, keeping the link.
2. **Every field the agent writes into a committed record is redacted** when `braindump.redact_secrets` is on: a rule's title and assertion and its draft ADR, a decision's title, context, decision and consequences, as well as the origin text and dead-end fields as before. The test code isn't: the person reviews it, and redacting it would change what runs.
3. **`context --json` has a `planned` key,** the same shape as `get_constraints` (`braindump.planned_payload()`, which both use and which never raises).
4. **A fence closes only on a line of the same character, at least as long, with nothing else on it** (CommonMark). ```` ```python ```` inside a fence doesn't close it.
5. **The parser records which lines each note came from,** and tidy removes exactly those, plus blank lines between them. A note written twice goes both times; the same words elsewhere stay.
6. **`enabled_here(root, scope)`:** for `local`, any scope counts (it is on for this user); for `project`, only a `project` entry for this repository does.

**Alternatives considered:**
- *Only the run-time check for the path:* a link needs it anyway, but the config check gives a clear error when the file is loaded, not a silent "no notes".
- *Redact the test code too:* it is hashed when approved and must run as reviewed; a secret in it is visible in review.

## Enforced Invariants

None new. Covered in `tests/test_braindump.py` (path, links in and out, redaction of every field, fences, tidy, `context --json`) and `tests/test_claude_plugin.py` (project scope).

## Consequences

- A config whose `braindump.path` is outside the repository no longer loads; the error says why.
- Notes containing a code block with a longer fence may get new ids, because the block is now one note. A note already sorted would then show as new once.
- `--plugin-scope project` now writes the committed settings when only you had the plugin on.
