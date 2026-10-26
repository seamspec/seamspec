---
id: ADR-20261024-b3e9
title: Release rehearsal findings - licence in the packages, notes below the BRAINDUMP marker pointed out
status: ACCEPTED
date: 2026-10-24
scopes: ["pyproject.toml", "seamspec/core/braindump.py", "seamspec/cli.py", "seamspec/mcp_server.py", "docs/SPEC.md"]
invariants: []
supersedes: null
superseded_by: null
---

# Release rehearsal findings - licence in the packages, notes below the BRAINDUMP marker pointed out

## Context

Release step 2 (2026-10-24) built the wheel and the sdist the way PyPI would receive them and installed the wheel into a clean environment, with no checkout and no editable install. In a fresh `uv init --lib` project it then ran everything that needs no agent:
- `init` with all four editors, CI and the plugin; the plugin was installed in a throwaway `CLAUDE_CONFIG_DIR` through `SEAMSPEC_PLUGIN_MARKETPLACE` (ADR-20261023-7d41);
- `doctor`, `propose`, `verify --proposed`, approve, `verify`;
- the pre-commit check refusing a violating commit;
- the stop hook of all four editors;
- the MCP server over stdio;
- the session-start hook, `drain`, a dead end, `status`, `spec`;
- running `init` again.

All of it worked from the installed package: nothing was missing, and the sdist holds only the package, README and `pyproject.toml`. It found five problems.

## Decision

1. **The licence travels with the packages.** Neither the wheel nor the sdist contained `LICENSE`, which Apache-2.0 asks for. `pyproject.toml` now sets `license-files = ["LICENSE"]`, which puts it in the sdist and in the wheel's `.dist-info/licenses/` and adds `License-File` to the metadata. A new `tests/test_packaging.py` builds both and checks three things: the licence is there, every tracked file under `seamspec/` is in the wheel, and the sdist holds nothing from outside the package. It is skipped without `uv`.
2. **`verify --proposed` no longer says "on the staged files".** The loop over proposals reused the name `staged` (the flag for a commit check on git's index) for the proposal it placed. The tests did run on the files on disk, but the message said otherwise, and a failing proposal would have told the agent to "stage it again". Bug fix; the test now checks both messages.
3. **The MCP server reports its version.** It sent an empty `serverInfo.version`; it now sends the package version, which editors show in their MCP lists. Bug fix; checked over stdio.
4. **Notes typed below the BRAINDUMP marker are pointed out** (new, SPEC §13.7). The rehearsal typed two notes at the end of the file, the natural place, which is SeamSpec's log. They were silently ignored: `drain` said "nothing new to sort". The explanation is inside an HTML comment that rendered Markdown hides. Any line below the marker other than the heading and log lines is now reported by `seamspec drain` (also `below_marker` in `--json`), `seamspec status` and `braindump_pending`. The MCP tool adds "Tell the user; never edit the file yourself.", because the agent must never edit the file (§13.2).
   - *Alternative: read notes below the marker too.* `tidy` would then have to tell the person's lines from its own log in the same section, and the person's text would sit in the part SeamSpec rewrites.
   - *Alternative: a visible "write above this line" in the template.* Any visible text above the marker is parsed as a note.
5. **README links for PyPI** (deferred to release step 5). The README has 14 relative links (`docs/…`, `LICENSE`). They work on GitHub but not on pypi.org, which shows the README as the project description. They become absolute GitHub links in the version PR, together with the install text.

## Enforced Invariants

None. Covered by `tests/test_packaging.py`, `tests/test_braindump.py` (CLI and MCP), `tests/test_trust_gate.py` and `tests/test_mcp_server.py`.

## Consequences

- The licence ships with every copy from PyPI.
- A person who types at the end of BRAINDUMP.md hears about it, from `drain`, from `status`, or from their agent when they ask it to sort the notes.
- Not yet covered by the rehearsal: an agent session in each editor running from the installed package (BRAINDUMP sorting, a rule proposed from chat, the stop hook sending the agent back), and the plugin fetched from GitHub at a tag. The owner runs the first by hand; the second needs the public repository and a tag. TestPyPI stays optional; it needs the owner's account.
