---
id: ADR-20261014-6c2d
title: "Fixes from the Antigravity hands-on test: project folder for the server, tool fallbacks, drain --dismiss"
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-14
scopes: ["seamspec/installers/hosts.py", "seamspec/templates/directive.md", "seamspec/templates/commands/drain.md", "seamspec/cli.py", "seamspec/core/doctor.py", "seamspec/core/lifecycle.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261014-6c2d: Fixes from the Antigravity hands-on test

## Context

The owner tried SeamSpec in Antigravity on a fresh project (`bdtest`, a small cart with BRAINDUMP notes). The session-start summary, sorting notes, approving rules, `/seamspec-status`, the agent declining a rule-breaking change and the Stop check blocking one all worked. Five things didn't:

1. **Every SeamSpec tool call failed** with *"calling tools/call: unexpected end of JSON input"* (Antigravity's log, from the first call at 10:43). Antigravity starts MCP servers in `/`. From there SeamSpec's server can't find the project, so it asks the client which folders are open (`roots/list`, ADR-20261011-d4a1), and Antigravity fails on that request. The same server answers normally when called directly, both from the project and from `/` with a client that answers `roots/list`.
2. **With the tools broken, the agent improvised.** It ran `seamspec` commands through Python and then searched `~/.gemini` for MCP settings, which can hold other services' keys. Nothing in SeamSpec's instructions said what to do when the tools are missing.
3. **Without the tools, a sort can't finish.** `seamspec drain --json` lists notes, but no command sets a note aside as a task or an idea.
4. **A stale server after re-creating the folder.** Antigravity kept a server started for an earlier copy of the folder until it was restarted in its MCP panel.
5. **The plugin question during `init --hosts antigravity`** asked about Claude Code with no word on why. Separately, the dead end from a note stored the agent's rewording as the note's preview, not the note.

## Decision

1. **`init` writes the project's absolute path into Antigravity's MCP config** (`env.SEAMSPEC_ROOT`), so the server never needs `roots/list`. Antigravity's config has no `${workspaceFolder}`, which VS Code's has. A rerun updates the path in SeamSpec's own entry (same command and args) and keeps any other keys in it; an entry with a different command is left alone ("kept (yours)"). `doctor` warns when the path isn't this folder (a clone elsewhere, or a teammate's committed config). Cursor is left as it is until its own hands-on test shows whether it needs the same.
2. **Protocol rule 5 says what to do without the tools:** use the matching `seamspec` command in the shell; never search outside the project for SeamSpec's settings; if neither works, stop and tell the user. The drain steps name the commands (`seamspec propose`, `propose-decision`, `dead-end`, each reading the tool's fields as JSON on stdin).
3. **`seamspec drain --dismiss ID=todo|exploration`** (repeatable) sets notes aside, the same as `braindump_pending(dismiss=…)`.
4. **`init --hosts …` adds a line:** if the tool already had the folder open, restart the `seamspec` server in its MCP settings (or reload the window).
5. **Wording:** the plugin screen says the plugin is for Claude Code only, and the question adds *"(Skip it if you don't use Claude Code.)"*. A record made from a note stores the note's own text from the file as its preview (redacted when `redact_secrets` is on).

**Alternatives considered:**
- **A server-side fallback when `roots/list` fails:** the failure happens inside Antigravity, so the server never gets an answer to fall back from.
- **A relative path, or `cwd`, in the config:** Antigravity documents neither for MCP servers, and the server's own folder is `/`.
- **Leaving tool failures to the agent's judgement:** it reached into the person's home folder, which SeamSpec must never prompt.

## Enforced Invariants

None yet.

## Consequences

- **The absolute path makes `.agents/mcp_config.json` machine-specific.** A team that commits it sees the path change when someone else reruns `init`; `doctor` explains the warning. This is the price of Antigravity starting servers outside the project.
- Rule 5 is three lines longer in `CLAUDE.md` and `AGENTS.md`; the new lines are recorded in `directive_known_lines.txt`.
- Still open from the same test, in later PRs: a cap on decisions per sort, rejecting several pending items at once, offering to sort notes again after the offer went unanswered, planned rules for notes whose code doesn't exist yet, and a read-only reviewer for VS Code and Antigravity. The commit-check gap the test also found is fixed in ADR-20261014-3b1e.
