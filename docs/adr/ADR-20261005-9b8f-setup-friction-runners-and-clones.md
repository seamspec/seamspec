---
id: ADR-20261005-9b8f
title: Less setup friction - project tools without activation, one question on a fresh clone
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-05
scopes: ["seamspec/core/verifier.py", "seamspec/cli.py", "seamspec/installers/scaffold.py", "seamspec/installers/git_hooks.py", "seamspec-plugin/scripts/**"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261005-9b8f: Less setup friction - project tools without activation, one question on a fresh clone

## Context
Hands-on testing (PR #18 sessions and the owner's demo repos) showed setup friction that has nothing to do with the core idea:

- The runner presets call `pytest` / `npx` from `PATH`. Hooks run inside Claude Code, the desktop app is started from the Dock, and GUI git clients start with a bare `PATH`, so a project's `.venv` is usually not on it. The verifier then reports "runner executable not found", or runs a different pytest than the project's.
- The plugin wrappers and the git pre-commit hook look for the `seamspec` CLI on `PATH`. `uv tool install` puts it in `~/.local/bin`, which apps started outside a shell often lack, so the hook silently does nothing.
- A teammate's fresh clone needs two separate steps: `seamspec init` (auto-run consent) and then `seamspec trust` (the committed runner commands). Both are "may SeamSpec run these things on my machine?".

Installing and enabling the Claude Code plugin from `init` and approving in chat are separate decisions (follow-up PRs).

## Decision

1. **Project tool folders go ahead of `PATH` for test runs.** `build_env(cfg, root=...)` prepends the folders that exist among `.venv/bin`, `.venv/Scripts`, `venv/bin`, `venv/Scripts`, `node_modules/.bin`, and the runner's `argv[0]` is resolved against that `PATH`. Config stays portable (still `pytest`, not `.venv/bin/python`). **An activated virtualenv wins:** when `VIRTUAL_ENV` is set, `.venv` / `venv` are not prepended. The red-green worktree already links these folders, so it resolves the same way.
2. **The plugin wrappers and the pre-commit hook append `$HOME/.local/bin` to `PATH`** before looking for `seamspec`. Appended, not prepended: a `seamspec` the user put on `PATH` still wins.
3. **On a fresh clone, `init` asks one question.** In an interactive terminal, when `.seamspec/config.toml` already exists and this machine hasn't trusted it, the consent screen also lists the runner commands, env passthrough and the number of locked tests (what `seamspec trust` shows), and asks *"Allow automatic test runs with these commands in this repository?"*. Yes records consent **and** trust; no records neither. `--accept-auto-run` stays consent only: trusting someone else's committed commands still needs a human at a terminal (`seamspec trust`).
4. **The yes is bound to what was shown** (from Copilot's review of PR #19). The CLI passes the trust hash of the displayed settings; `init` grants trust only if the config on disk still hashes the same. `--mode strict` on an advisory clone (which switches `trust_level` to `harness`) or an edit while the prompt is open therefore trusts nothing, and `init` says to run `seamspec trust`.
5. **Committed config is printed escaped** on both trust screens: tokens beyond plain characters are JSON-quoted, so newlines and terminal escapes in a clone's config can't repaint the screen being trusted, and argv token boundaries stay visible (Copilot, PR #19).
6. **No empty `PATH` entry.** The wrappers and the hook use `PATH="${PATH:+$PATH:}$HOME/.local/bin"`: with an empty `PATH`, `$PATH:` would add an empty entry, which means the current folder, so a checkout could plant its own `seamspec` (Copilot, PR #19). A runner's own `env.PATH` also gets the project tool folders in front of it.

**Alternatives considered:**
- *Write `.venv/bin/python -m pytest` into `config.toml` at `init`:* rejected. The config is committed; the path is OS-specific and differs per machine (`uv`, Poetry, pyenv, Windows).
- *Use `uv run pytest` when `uv.lock` exists:* rejected for now. It can sync dependencies (network, slow) inside a time-limited Stop hook, and it only covers uv projects.
- *Prepend `~/.local/bin` in the wrappers:* rejected; it would override the user's own choice of `seamspec`.
- *Let `--accept-auto-run` also trust a clone:* rejected; that would let a script approve commands a human never saw (§12.4.6).

**Security note:** a tool in the project's `.venv` can be replaced by anything with write access to the working tree, including the agent. That was already true (the agent can edit the venv's pytest package, or the code under test), so this adds no new capability; CI, which builds its own environment, remains the backstop (§12.4.8).

## Enforced Invariants
None yet. Dogfooding candidates: "a runner resolves from the project's .venv without activation", "scripted init never trusts a clone".

## Consequences
* Python projects with a `.venv` work in Claude Code, the desktop app and GUI git clients without activating anything.
* A teammate's onboarding is `seamspec init` with one yes.
* SPEC §12.4.5, §12.4.7, §16.1, §16.4, §19.6 and §19.7 are updated in the same PR.
