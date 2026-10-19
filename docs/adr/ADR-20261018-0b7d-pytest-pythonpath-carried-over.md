---
id: ADR-20261018-0b7d
title: "SeamSpec's pytest.ini carries over the project's own pytest pythonpath"
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-18
scopes: ["seamspec/core/runners.py", "seamspec/installers/scaffold.py", "seamspec/core/doctor.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261018-0b7d: SeamSpec's pytest.ini carries over the project's own pytest pythonpath

## Context

The second capture calibration (`calib-capture-3`, after ADR-20261018-6e1a) went much further. The agent logged the dead end and proposed all three agreements as rules right after the first prompt. But none of the three rule tests could run:
- they import `jobqueue` by name, as SeamSpec's import hint tells them to for a `src/` project;
- the project makes `src/` importable the common way, with `pythonpath = ["src"]` in its own pytest settings, and isn't installed in its virtualenv;
- SeamSpec runs rule tests with its own `.seamspec/pytest.ini` (with `--noconftest`, so the project's conftest and addopts never apply to locked tests), and that file only put the repository root on the path.

So the agent's tests failed to import, the scripted reviewer rejected them, and nothing was captured. The agent tried to install the project, which the benchmark doesn't allow, and said the tests couldn't be verified. Any real project set up this way hits the same wall: SeamSpec's rule tests can't import what the project's own tests can.

## Decision

1. `init` reads the folders the project's own pytest settings add to `sys.path`:
   - `pythonpath` in `pyproject.toml`'s `[tool.pytest.ini_options]` (list or string);
   - `pytest.ini`;
   - `setup.cfg`'s `[tool:pytest]`;
   - `tox.ini`'s `[pytest]`.

   It keeps only relative folders inside the repository that exist and aren't the root, and writes them into `.seamspec/pytest.ini` after the root (`pythonpath = .. ../src`).
2. **The import hint** for a `src/` project says the package is importable because SeamSpec's pytest.ini adds `src/`, as the project's settings do. Only when it doesn't does the hint keep the old "installed in its virtualenv; if the import fails, install it first".
3. **`doctor` warns** when the project's pytest settings add a folder that `.seamspec/pytest.ini` doesn't. That's an older setup, since `init` never rewrites that file: it's fingerprinted, and a change goes through `seamspec review`.

**Alternatives considered:**
- **Install the benchmark's projects into their virtualenvs** (what `uv sync` would do): it would hide the gap from the benchmark while every real project configured with pytest's `pythonpath` still hit it.
- **Let SeamSpec's pytest run read the project's pytest settings:** it would also bring in addopts and plugins that SeamSpec keeps out of locked tests on purpose.
- **Rewrite an existing `.seamspec/pytest.ini` on rerun:** runner config is fingerprinted, so a silent rewrite would fail every locked rule until confirmed. `doctor` says what to add, and review confirms it.

## Enforced Invariants

None yet.

## Consequences

- In such projects, rule tests import the code the same way the project's own tests do.
- **Existing setups** keep their file until the person adds the folder; `doctor` tells them.
- The capture calibration is rerun (`calib-capture-4`, about $0.60) before the counted runs.
