---
id: ADR-20261105-9d3f
title: Agents may not edit SeamSpec's reviewer and command files, and changes to them are reported
status: ACCEPTED
date: 2026-11-05
scopes: ["seamspec/core/commands.py", "seamspec/core/scope.py", "seamspec/installers/hosts.py", "seamspec/core/doctor.py", "seamspec/cli.py", "seamspec/adapters/claude.py"]
invariants: []
supersedes: null
superseded_by: null
---

# Agents may not edit SeamSpec's reviewer and command files, and changes to them are reported

## Context

The owner asked whether the reviewer's instructions behind `/seamspec-explain` can be tampered with. They can. For Cursor, VS Code and Antigravity, `init` writes the reviewer and the `seamspec-*` commands as plain files in the project (`.agents/agents/seamspec-reviewer.md` and so on). Only `.seamspec/` was protected from agent edits, and `doctor` never compared these files with what SeamSpec writes. The person who installed SeamSpec may change them; that is their call. The risk is the working agent quietly softening the reviewer, say by deleting "don't argue it away here" (ADR-20261105-e2c9), so its own rules look sound. The edit would show only in a diff someone has to notice.

## Decision

- **The edit hook refuses agent edits** to every file SeamSpec writes whole for another host: its commands or skills and its reviewer (`commands.GENERATED_GLOBS`, added to `effective_protected_paths()`). The refusal says `seamspec init` rewrites them. Files without the `seamspec-` prefix, the project's own agents and commands, stay editable.
- **`doctor` warns** (locally) when one of these files differs from what this SeamSpec writes, and names `seamspec init --hosts <host>`.
- **Every commit check warns too, without blocking.** Cursor, VS Code and Antigravity have no edit hook yet (their edit tools aren't documented, §16), so on those hosts the refusal above never fires. The commit check runs whichever agent made the change, so it is where every host's edit becomes visible.

Alternatives: blocking the commit, rejected because a teammate on another SeamSpec version would have their commits refused for text they didn't write; checking in CI, rejected for the same reason, since CI's SeamSpec version can differ from the one that wrote the files.

## Enforced Invariants

None new.

## Consequences

- An agent in Claude Code can't change another host's reviewer or commands by editing them. In every host, a change shows up in `doctor` and at each commit until someone looks at it or reruns `init`.
- After a SeamSpec upgrade, the same warning appears until `init --hosts` is rerun, which also tells people to update.
- Not covered: shell commands (no edit hook stops those, §7.1); the merged hook and MCP config files, which hold the project's own entries too; CODEOWNERS for these files in strict mode (a follow-up); the Claude Code plugin's own copy, which lives outside the project and is replaced on update.
