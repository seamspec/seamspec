---
id: ADR-20261011-d4a1
title: The MCP server finds the project of a session that was moved to another folder
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-11
scopes: ["seamspec/mcp_server.py", "seamspec/core/root.py", "seamspec/adapters/claude.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261011-d4a1: The MCP server finds the project of a session that was moved to another folder

## Context

Dogfooding finding #2 (2026-10-08). A Claude desktop session started without a project folder, in the app's scratch folder, and was later moved to the owner's project. SeamSpec's tools then answered `not_a_seamspec_project` and named the scratch folder. The agent worked around it with the `seamspec` command; a new session started in the project worked.

**What the Claude Code docs say** (MCP and permissions pages, checked 2026-10-11):

- When a session is moved (`/cd`), Claude Code applies the new folder's configuration, including *"the plugins its settings enable"*, and connects those plugins' MCP servers. So the SeamSpec server starts at the move, in a session that was launched elsewhere.
- `${CLAUDE_PROJECT_DIR}`, which the plugin passes to the server as `SEAMSPEC_ROOT`, is *"the project root where the session started"* and *"doesn't change"*. After a move it still names the launch folder.
- Claude Code answers the MCP `roots/list` request with *"the session's launch directory plus every additional working directory"*.
- Hooks get the current folder in every payload (`cwd`), which is why SeamSpec's hooks kept working in the moved session.

The docs don't say which folder a stdio server process is started in, nor whether the folder a session was moved to is among its roots.

## Decision

1. **The server looks further when the launch folder isn't a SeamSpec project.** Per call, in this order:
   1. `$SEAMSPEC_ROOT`, or a folder above it;
   2. the folder the server process was started in, or a folder above it;
   3. the session's folders, as the client reports them (`roots`), and any absolute file path in the call (`get_constraints(files)`). If exactly one SeamSpec project is found there, it is used.
2. **The client is asked for its folders only when steps 1 and 2 fail,** so the usual call makes no extra round trip. The request rides the SDK's resolver mechanism: a parameter the server fills in, which is not part of any tool's input schema, so it costs no tokens. A client without `roots` isn't asked.
3. **Two SeamSpec projects among the session's folders are not guessed.** The call fails and names both.
4. **A clear message when nothing is found:** which folder the tools are tied to, that it has no `.seamspec/config.toml`, and to start a new session in the project.
5. **A session moved from one SeamSpec project to another gets a warning from the hooks.** There the launch folder *is* a SeamSpec project, so the server keeps answering for it and can't notice. The hooks can: they get the current folder in the payload and the launch folder in `CLAUDE_PROJECT_DIR`. When those are two different projects, the edit-time context and the session-start summary say that the rules shown are for this project, that the tools still answer for the other one, and to use the `seamspec` command until a new session is started here. Enforcement is unaffected: the Stop gate and the edit-time context already follow the current folder. The warning doesn't depend on there being rules to show: a project with an empty ledger still gets it at session start, and once at the first edit of the session (from Copilot's review of #49).

**Alternatives considered:**
- **Prefer the server's own folder over `SEAMSPEC_ROOT`.** Rejected: the docs don't say where a server starts, while they do define `CLAUDE_PROJECT_DIR`.
- **Have hooks tell the server the current folder through a file.** The server and the hooks share no session id, and keying on the launch folder or a parent process is guesswork that could point at the wrong project.
- **A `use_project(path)` tool for the agent.** It adds tool-definition tokens and lets the agent choose which project's rules it sees.
- **Ask for `roots` on every call.** An extra round trip each time, for a case that is rare.

## Known limits

- `open_review` and the two ADR resources use steps 1 and 2 only. `open_review` runs its own multi-round flow, which the SDK doesn't let a tool combine with resolver parameters.
- MCP marks `roots` as deprecated from protocol 2026-07-28 on. Claude Code still supports it; if it goes away, steps 1, 2 and the file-path hint remain.
- **Checked in real sessions on 2026-10-11** (Claude Code 2.1.296, Claude Haiku 5.5, two runs, about $0.012 on the plan login; a probe MCP server reported what a server sees):
  - a session launched in a folder that isn't a SeamSpec project, with the project given as an additional folder (`--add-dir`): the server was started **in the launch folder**, `CLAUDE_PROJECT_DIR` was the launch folder, and `roots` listed the launch folder and the project. `get_constraints` then found the project through `roots` and returned its rule. Step 3 of the lookup works end to end.
  - with no project among the session's folders, the agent received the message of point 4 and reported "start a new session in your SeamSpec project folder" as the next step.
- **Still not checked:** a session moved with `/cd`. Non-interactive sessions answer *"/cd isn't available in this environment"*, so it couldn't be scripted. The open point is whether the folder a session is moved to appears among its `roots`. If it doesn't, the moved session gets the message of point 4 instead of working tools.

## Enforced Invariants

To be proposed: "a tool call never answers for a project the session isn't in without saying so" is too broad to test; the testable part is "with two SeamSpec projects among the session's folders, the tools refuse instead of picking one".

## Consequences

* SPEC §14.3, §16.1, §19.1 and §19.11 are updated. Finding #2 in `docs/PROGRESS.md` is fixed as far as it can be tested without a real session.
* `root.project_at(start)` is new; `find_root` (the CLI) is unchanged.
* The test suite clears `CLAUDE_PROJECT_DIR`, so it behaves the same inside and outside a Claude Code session.
