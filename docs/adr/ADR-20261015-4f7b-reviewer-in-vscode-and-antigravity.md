---
id: ADR-20261015-4f7b
title: "SeamSpec's reviewer in VS Code and Antigravity, as each tool's own read-only agent"
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-15
scopes: ["seamspec/core/commands.py", "seamspec/installers/hosts.py", "seamspec/installers/directive.py", "seamspec/templates/agents/reviewer.md", "seamspec/templates/commands/_explain-vscode.md", "seamspec/templates/commands/_explain-antigravity.md"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261015-4f7b: SeamSpec's reviewer in VS Code and Antigravity

## Context

ADR-20261013-b7d2 shipped `/seamspec:explain` and the read-only reviewer agent in the Claude Code plugin only, and ADR-20261013-e8f3 left it out of the other hosts. While testing Antigravity, the owner asked why the other tools can't have it too. Their public docs (read 2026-10-15) show that VS Code and Antigravity can define custom agents with a tool allowlist. Cursor can as well, but its read-only switch also blocks every MCP tool, and its forum reports bugs with read-only subagents.

What the docs say:
- **VS Code** (`code.visualstudio.com/docs/copilot/customization/custom-agents`, `…/prompt-files`, `…/agents/reference/tools-reference`):
  - Custom agents live in `.github/agents/*.agent.md`, with `name`, `description`, `tools` (tool sets such as `read` and `search`, MCP tools, `<server>/*` for a whole server) and `agents` (`[]` for no subagents).
  - VS Code ignores a tool it can't find.
  - A prompt file can run in a named custom agent (`agent: <name>`).
- **Antigravity** (`antigravity.google/docs/subagents`):
  - Custom subagents live in `.agents/agents/<name>.md`, with `name`, `description`, `tools` (an explicit allowlist; documented names include `view_file` and `grep_search`), `mainAgent`, `subagent` and `commandExecutionPolicy` (`off | auto | eager | sandbox`).
  - The main agent starts one with `invoke_subagent`.
  - The page names no MCP tool for an allowlist and warns that an unmapped tool name can hang the subagent.

## Decision

`seamspec init --hosts` writes the reviewer, from the same prompt as Claude Code's, as each tool's own agent:

1. **VS Code:** `.github/agents/seamspec-reviewer.agent.md` with `tools: ['read', 'search', 'seamspec/review_material']` and `agents: []`. `/seamspec-explain` is a prompt file with `agent: seamspec-reviewer`, so the reviewer answers the user **directly**, with no working agent relaying it. That is stronger than Claude Code's relay.
2. **Antigravity:** `.agents/agents/seamspec-reviewer.md` with `tools: [view_file, grep_search]`, `commandExecutionPolicy: "off"`, `subagent: true` and `mainAgent: false`. `/seamspec-explain` is a skill telling the working agent to start it with `invoke_subagent` and relay its answer unchanged, as in Claude Code.
3. **Without `review_material`, the reviewer reads the ledger itself.** The shared prompt gains one paragraph saying where each kind of item lives on disk. Antigravity always works this way; VS Code does if it can't resolve the tool name.
4. **Cursor:** no reviewer and no `/seamspec-explain` yet. `AGENTS.md`, which all three read, offers the reviewer "where your tool has it". The `lock`, `supersede` and `drain` commands keep their "offer an explanation" lines in VS Code and Antigravity, and lose them in Cursor.

**Alternatives considered:**
- **Giving Antigravity's reviewer SeamSpec's MCP server through its `mcpServers` field:** the allowlist would still need a tool name the docs don't give, and a wrong one can hang the subagent.
- **Adding `run_command` so it could run `seamspec` itself:** it would no longer be read-only.
- **The working agent calls `review_material` and passes the result to the reviewer:** the author would sit between the material and the reader, which is what the reviewer exists to avoid.
- **A Cursor reviewer with only file reading:** possible, but given the reported read-only bugs it should wait for a hands-on check.

## Enforced Invariants

None yet.

## Consequences

- VS Code and Antigravity users get the same independent explanation before `seamspec review`. Antigravity's lacks SeamSpec's test facts and the diff, so it says less about what changed.
- **Untested inside the tools.** These formats come from the docs. The VS Code tool name `seamspec/review_material` and Antigravity's `commandExecutionPolicy: "off"` are the parts most likely to need a fix after the owner's hands-on check.
- `commands.CLAUDE_ONLY` becomes `NEEDS_REVIEWER`, with `REVIEWER_HOSTS` and `has_reviewer()`.
