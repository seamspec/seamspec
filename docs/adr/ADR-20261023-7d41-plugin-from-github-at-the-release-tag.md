---
id: ADR-20261023-7d41
title: A released SeamSpec takes the Claude Code plugin from GitHub at its own tag; project scope for teams
status: ACCEPTED
date: 2026-10-23
scopes: ["seamspec/installers/claude_plugin.py", "seamspec/cli.py", "docs/SPEC.md"]
invariants: []
supersedes: null
superseded_by: null
---

# A released SeamSpec takes the Claude Code plugin from GitHub at its own tag; project scope for teams

## Context

`seamspec init` installed the Claude Code plugin only when the CLI ran from a checkout, because the checkout was the plugin marketplace (ADR-20261005-428a). A SeamSpec installed from PyPI has no checkout, so it skipped the plugin with "the plugin ships with the release". After the release that would be wrong for everyone: the Claude Code plugin is how SeamSpec works in Claude Code. ADR-20261005-428a left two things for the release: a published marketplace, and `project` scope so a team gets the plugin from the committed settings.

This was found while listing the steps before going live (2026-10-23). It is the first of them.

## Decision

1. **Where the plugin comes from**, in this order:
   - `$SEAMSPEC_PLUGIN_MARKETPLACE`, when set: any source `claude plugin marketplace add` accepts. It is for release rehearsals, such as installing the built wheel and pointing it at a checkout or a branch.
   - The checkout the CLI runs from (an editable install), as before.
   - For a **released** version (the same test the CI workflow uses, `ci.released()`): this repository on GitHub, pinned to that version's tag, `https://github.com/seamspec/seamspec.git#v<version>`. The plugin and the installed CLI then always match. HTTPS, because the `owner/repo` form tries SSH first and, inside a session or on update, doesn't fall back for users without a GitHub SSH key.
   - Otherwise (an unreleased build installed without a checkout) there is no tag to pin to: skipped, with how to install from a checkout.
2. **Team scope.** `seamspec init --plugin-scope project`, or *yes* to a new question after the install question, *"Turn it on for everyone who works in this repository? … [y/N]"*, runs both commands with `--scope project`. Claude Code then writes the committed `.claude/settings.json` (`extraKnownMarketplaces` with the git URL and the tag, plus `enabledPlugins`), and each teammate's Claude Code offers the plugin once they trust the folder. The question defaults to no, because it changes a shared, committed file. It is asked only when the source can be shared: a path on this machine never goes into a committed file, and `--plugin-scope project` with such a source is skipped with a note. When the answer changes the scope, `init` shows the `project` commands before running them, so nothing runs that wasn't shown.
3. **Tag naming.** Releases are tagged `v<version>` (`v0.1.0`), and the tag must contain the matching `.claude-plugin/marketplace.json` and `seamspec-plugin/`. The release step creates it.
4. A wrong `--plugin-scope` value is refused before `init` changes anything.

**Checked with the real Claude Code CLI (2.1.296)**, in a throwaway `CLAUDE_CONFIG_DIR`, against a public GitHub marketplace (`anthropics/claude-code`), since our repository is still private and has no tag:
- `marketplace add https://…git#<tag> --scope project` clones that tag and writes only the URL and the `ref` into `.claude/settings.json`; no machine path.
- Adding the same marketplace again at another tag moves the pin and says so.
- `file://` sources are refused, so the pinned path can't be tested end to end against a local repository. It will be tested for real once the repository is public and tagged (release rehearsal, step 2 of the release list).

**Alternatives considered:**
- *Ship the plugin inside the wheel and point the marketplace at the installed package folder.* It works without a public repository, but the path is machine-specific, so it can never go into the committed settings for a team, and every upgrade moves it.
- *Track `main` instead of a tag.* Users would get plugin changes before the matching CLI is on PyPI.
- *Make team scope the default.* It writes a committed file; that should be a deliberate yes.

## Enforced Invariants

None. Covered by `tests/test_claude_plugin.py`: the release source and its tag, the environment override, which sources can be shared, project scope with a release, project scope refused for a path, the flag, a wrong flag value changing nothing, and the team question (yes, no, default).

## Consequences

- After the release, `uv tool install seamspec` then `seamspec init` sets up the Claude Code plugin, for one person or the whole team.
- The repository must be public for users to fetch the plugin. That is already planned before the release.
- **Upgrades are not handled yet.** Re-running `init` after upgrading SeamSpec reports the plugin as unchanged, so it stays pinned to the old tag. The plugin is a thin layer that calls the installed `seamspec`, so an old pin mostly keeps working, but skill and hook changes wouldn't arrive. Before a second release ships, `init` (or `doctor`) must notice the old tag, move the pin and update the plugin. This is in PROGRESS.
- The README and getting-started still describe installing from a clone; they switch to `uv tool install seamspec` in the release PR, so they are never wrong in between.
