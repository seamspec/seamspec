---
id: ADR-20261011-e7c5
title: Runner hints fit the project - how to import its code, and which program a runner resolves to
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-11
scopes: ["seamspec/core/runners.py", "seamspec/mcp_server.py", "seamspec/templates/runners/**"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261011-e7c5: Runner hints fit the project - how to import its code, and which program a runner resolves to

## Context

Dogfooding finding #3 (2026-10-10), in a Python project with a `src/` layout managed by `uv`. Two things misled the agent:

1. **The import hint was one fixed sentence:** *"Import project code from the repo root, e.g. `from src.queue import backoff_delay`"*. That fits a project where `src/` is itself a package. In a `src/` layout the package is installed into the virtualenv and imported by its own name; `from src.<package> import …` would load a second copy of the modules under a different name. The owner had to tell the agent.
2. **The agent concluded SeamSpec's runner would fail.** It read `cmd = ["pytest", …]` in `.seamspec/config.toml`, found no `pytest` on its `PATH`, and reported that the config needed changing. In fact the verifier puts the project's `.venv/bin`, `venv/bin` and `node_modules/.bin` first on `PATH` without activation (§12.4.7). Nothing told the agent so.

## Decision

1. **The pytest import hint is chosen from the project's layout** (`runners.python_layout(root)`):

   | Layout | Detected by | Hint |
   |---|---|---|
   | `src/` is a package | `src/__init__.py` exists | as before: `from src.queue import …` |
   | Packages under `src/` | a folder with `__init__.py` inside `src/` | import the package by name, never `src.<package>`; it works because the project is installed in its virtualenv; if the import fails, install it first |
   | Packages at the root | a folder with `__init__.py` at the root (not `tests`, `docs`, `scripts`, …) | `from <package> import …`, the root is on `sys.path` |
   | Nothing recognisable yet | none of the above | from the root, or by package name if the project is installed |

   The example names a real package of the project: the one matching `[project] name` in `pyproject.toml`, else the first found.
2. **`get_constraints` says which program each runner resolves to.** A new `command` field per runner: *"`pytest` resolves to .venv/bin/pytest. SeamSpec looks in the project's .venv, venv and node_modules/.bin first, without activation, so config.toml needs no change."*, or that the program wasn't found and must be installed in the project. It is resolved the way the verifier resolves it.
3. **New configs say it too:** `init` writes a comment above each runner's `cmd` about where the program is looked up.

**Alternatives considered:**
- **Add `../src` to SeamSpec's `pytest.ini` for `src/` layouts.** It would make the package importable without installing it, but `pytest.ini` is written once at `init` (often before `src/` exists) and is fingerprinted; changing it later is a reviewed step, not something a hint should trigger.
- **Write absolute tool paths into `config.toml`.** They differ per machine, and the config is committed and trust-hashed.
- **Say nothing and rely on the agent trying it.** That is what happened, and it cost the owner a round trip.

## Enforced Invariants

To be proposed: "the import hint for a src/ layout never suggests importing through `src.`".

## Consequences

* SPEC §12A.6, §14.1 and §19.11 are updated; `runners.py` gains `python_layout` and `import_hint`.
* Existing projects get the better hints at once (they come from the tool, not from files). The comment in `config.toml` appears only in configs written from now on.
