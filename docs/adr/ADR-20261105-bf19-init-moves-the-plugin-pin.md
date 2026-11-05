---
id: ADR-20261105-bf19
title: Re-running init moves the Claude Code plugin to the installed version, and doctor warns when it hasn't
status: ACCEPTED
date: 2026-11-05
scopes: ["seamspec/installers/claude_plugin.py", "seamspec/cli.py", "seamspec/core/doctor.py"]
invariants: []
supersedes: null
superseded_by: null
---

# Re-running init moves the Claude Code plugin to the installed version, and doctor warns when it hasn't

## Context

A released SeamSpec installs the plugin from GitHub, pinned to its own tag, so the plugin and the CLI match (ADR-20261023-7d41). Nothing moved that pin on an upgrade: after `uv tool upgrade seamspec`, `init` reported *unchanged* and the plugin stayed on the old tag. This only matters once a second version exists, so it had to be fixed before 0.1.1.

## Decision

- **`init` moves it.** It compares this repository's settings file and `claude plugin list` with the installed version. If the pin or the installed copy differs, it runs `claude plugin marketplace add <source> --scope <scope>` and then `claude plugin update seamspec@seamspec --scope <scope>`, using Claude Code's own CLI as everywhere else.
- **It needs a yes**, like every change to Claude Code's settings: a question in a terminal, or `--plugin`. `--no-plugin`, or no terminal and no flag, changes nothing. `--plugin-scope` limits the move to that scope, so `local` never touches the committed file.
- **It checks the result** and reports `upgraded` only when it can see the new pin and version. If `claude plugin list` fails afterwards, that's `failed`, not success.
- **`doctor` warns** and names `seamspec init --plugin`, because people upgrade without re-running `init`. It runs `claude` only when this repository's settings already pin the plugin, so other projects pay nothing.
- **The installed copy counts, not just the pin.** A teammate may have committed the new tag while this machine still has the old plugin.
- **Left alone:** a checkout (it loads in place), a pin to another repository (someone's fork), and a `user` scope install, which covers every project on the machine, so one repository's `init` shouldn't change it.

Alternatives: an unpinned plugin that follows `main`, rejected because the plugin could then get ahead of the CLI; moving the pin silently, rejected because it changes settings without a yes; a check in the session-start hook, not done now because running `claude` there would slow every session.

## Enforced Invariants

None new.

## Consequences

- An upgrade still needs one more step, `seamspec init` or `seamspec init --plugin`, until something prompts for it at session start. The upgrade docs now say so.
- A moved `project` pin changes a committed file, so `init` says to commit it. Teammates on an older CLI then get the newer plugin until they upgrade too.
- Claude Code keeps one copy of a marketplace per machine, so two repositories pinned to different tags can pull it back and forth. Moving both repositories avoids that. This hasn't been seen in use.
- `$SEAMSPEC_PLUGIN_MARKETPLACE` is compared by its ref only, since it can point anywhere. Release rehearsals can use it to try a move.
