---
id: ADR-20261105-844f
title: A GEMINI.md suggests Antigravity, and Antigravity's MCP config stays out of git
status: ACCEPTED
date: 2026-11-05
scopes: ["seamspec/installers/hosts.py", "seamspec/core/doctor.py"]
invariants: []
supersedes: null
superseded_by: null
---

# A GEMINI.md suggests Antigravity, and Antigravity's MCP config stays out of git

## Context

Two problems came up while dogfooding on the owner's project, SessionWalk:

- **No offer to set up Antigravity.** The project had `GEMINI.md` but no `.agents` folder yet, so `init` never offered Antigravity and its `/seamspec-*` commands were missing. `init` looked only for the folder.
- **A committable file with a home path.** `.agents/mcp_config.json` holds the project's absolute path (ADR-20261014-6c2d), and `init` didn't ignore it. SessionWalk's agent had to add the ignore line by hand. Committed, it puts a home folder path, usually including a username, in the repository, and gives every other clone the wrong folder.

## Decision

- **`detect()` also treats a `GEMINI.md` as a sign of Antigravity.** Gemini CLI reads that file too, so the guess can be wrong; it only adds one yes/no question, which never runs without an answer.
- **`init --hosts antigravity` adds `.agents/mcp_config.json` to `.gitignore`.** Each clone writes its own copy, which it needed anyway, since `doctor` already warned when the path pointed at another folder.
- **An already committed copy isn't untracked automatically.** `init` prints `git rm --cached .agents/mcp_config.json`, and `doctor` warns until it's gone, since removing a file from the index is the person's call.
- **The rest of `.agents/` stays committable:** the hooks, skills and reviewer agent are the same on every machine.

Alternatives: a relative path in the config, which Antigravity doesn't support (no `${workspaceFolder}`, ADR-20261014-6c2d); running `git rm --cached` for the person, rejected because it changes what their next commit records.

## Enforced Invariants

None new.

## Consequences

- After cloning, a teammate runs `seamspec init --hosts antigravity` to get SeamSpec's tools in Antigravity. The hooks, commands and rules still come with the clone.
- Some Gemini CLI projects get one extra question.
- This amends ADR-20261014-6c2d, which assumed the file would be committed and rewritten in each clone.
