---
id: ADR-20261005-5009
title: Claude Code hook adapter, aligned with the current hooks reference
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-05
scopes: ["seamspec/adapters/**", "seamspec/core/session.py", "seamspec/core/tree.py", "seamspec/cli.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261005-5009: Claude Code hook adapter, aligned with the current hooks reference

## Context
Week 3's first slice implements `seamspec hook claude pre-tool-use|stop` (SPEC §7.2, §16.1). The spec flagged the hook payload and output fields as "verify against current docs". The Claude Code hooks reference (code.claude.com/docs/en/hooks, read 2026-10-05) differs from the spec in three places.

## Decision

1. **Stop retries are counted per user prompt (`prompt_id`).** The Stop payload no longer includes `stop_hook_active`; it has `prompt_id`, `stop_reason` and `last_assistant_message`. Each new user prompt gets a fresh `max_stop_retries` budget, which caps one task rather than a whole session. If an older Claude Code sends `stop_hook_active`, a stop with `false` still resets the count.
2. **The matcher is a plain list: `Edit|Write|MultiEdit|NotebookEdit`.** The reference says a matcher of only letters, digits and `|` is an exact list, not an unanchored regex, so no anchors are needed. `MultiEdit` stays for older versions; the adapter also ignores any other tool name itself.
3. **`additionalContext` on `PreToolUse` is the edit-time context mechanism.** The reference confirms it reaches the model as a system reminder. The `PostToolUse` on `Read` fallback is dropped (the reference also describes PostToolUse context as replacing the tool result, which would be worse). A hands-on check in a real session still happens with the plugin slice.
4. **The exit code is always 0; decisions travel in JSON.** Exit code 2 means "block" to Claude Code, so a crash must never produce it.
5. **Silent outside SeamSpec projects.** If the payload's `cwd` isn't inside a project with `.seamspec/config.toml`, the hook prints nothing. A user-level plugin then costs nothing in other repos.
6. **The Stop gate saves `last_verify.json`,** so `seamspec status` reflects the last in-session run.
7. **The tree fingerprint** is `HEAD` plus the content of changed and untracked, non-ignored files. Outside git it's `None`, which disables the "unchanged tree" skip rather than risking a stale pass.

**Alternatives considered:**
- *Count retries per session:* rejected; after three failed stops in one task, every later task in the same session would get no gate at all.
- *Keep the anchored regex matcher:* unnecessary; the plain list is exact and easier to read.

## Enforced Invariants
None yet. Candidates once SeamSpec governs its own repo: "edit-time context never returns a permission decision of `allow`", "the Stop gate never blocks more than `max_stop_retries` times per prompt".

## Consequences
* SPEC §16.1 (matcher, Stop steps 1–2), §19.10 (now a contract) and §26 "still open" #3 are updated in the same PR.
* The plugin slice uses these exact hook commands; its hands-on check confirms the context really appears in a session.
