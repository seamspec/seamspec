---
id: ADR-20261005-428a
title: seamspec init installs the Claude Code plugin at local scope, after asking
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-05
scopes: [".claude-plugin/marketplace.json", "seamspec/installers/claude_plugin.py", "seamspec/cli.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261005-428a: seamspec init installs the Claude Code plugin at local scope, after asking

## Context
Hands-on testing showed that installing SeamSpec takes two separate steps: install the CLI, then load the plugin with `claude --plugin-dir …` in every session. ADR-20261005-5675 planned a marketplace entry and an `init` hint for weeks 4–6. The owner moved setup friction ahead of dogfooding, and asked that nothing change their Claude Code settings without a yes.

Claude Code's CLI (checked against 2.1.291 in a throwaway `CLAUDE_CONFIG_DIR`) supports this directly:
- `claude plugin marketplace add <path> --scope local`
- `claude plugin install <plugin>@<marketplace> --scope local`

Both accept `--json`, and both are idempotent ("already on disk", "already installed"). `local` scope writes `extraKnownMarketplaces` and `enabledPlugins` to `<repo>/.claude/settings.local.json`. A `directory` marketplace loads the plugin in place. `claude plugin list --json` reports each install's `scope`, `enabled` and `projectPath`.

## Decision

1. **This repository is also the plugin marketplace:** `.claude-plugin/marketplace.json`, name `seamspec`, one plugin `seamspec` with source `./seamspec-plugin`. The plugin id is `seamspec@seamspec`. `claude plugin validate .` passes.
2. **`init` uses Claude Code's own CLI, never writes its settings files.** It runs `claude plugin marketplace add <checkout> --scope local`, then `claude plugin install seamspec@seamspec --scope local`.
3. **`local` scope only, for now.** It touches just this user and just this repository. `project` scope would commit an absolute path to the checkout into `.claude/settings.json`; it waits for a published GitHub marketplace at the release (ADR-20261005-3adc). `user` scope would turn the plugin on for every project; it is not offered.
4. **Asks first, shows the exact commands.** `--plugin` and `--no-plugin` exist for scripts. Without a terminal and without a flag, `init` calls nothing and prints `seamspec init --plugin`.
5. **`.claude/settings.local.json` goes into the repo's `.gitignore` whenever it exists.** It holds this machine's checkout path. Claude Code's own global ignore covers it on some machines, but not reliably. This also covers a plugin installed by hand (`init` reports `unchanged`) and an install that failed after `marketplace add` had already written the file (from Copilot's review of PR #20).
6. **Skip or no-op cases:**
   - `claude` isn't on `PATH` → skipped, with a note;
   - the CLI isn't running from a checkout → skipped (a wheel install has no marketplace until the release);
   - `claude plugin list` already shows it enabled for this repository or at `user` scope → unchanged.
7. **Tests can't touch the developer's Claude Code settings.** An autouse fixture gives every test its own `CLAUDE_CONFIG_DIR`. Most tests use a fake `claude`, and one test runs the real CLI in the throwaway config when it is installed.

**Alternatives considered:**
- *Edit `.claude/settings.local.json` ourselves:* rejected. The format belongs to Claude Code, and its CLI also populates the plugin cache.
- *Print the commands and let the human paste them:* that is the "no" path. The yes path removes a terminal round trip, which was the point.
- *Default to `user` scope:* rejected (decision 3).

## Enforced Invariants
None yet. Dogfooding candidate: "init never changes Claude Code settings without a yes or --plugin".

## Consequences
* Onboarding is now `uv tool install --editable <checkout>` then `seamspec init` with yes answers; no `--plugin-dir` is needed.
* The owner's "enable the plugin for this repo in this app" step becomes `seamspec init --plugin` in the SeamSpec repo, after dogfooding's `init`.
* SPEC §15, §16.1, §19.6a and §21 are updated in the same PR. ADR-20261005-5675 decision 9 ("marketplace and init hint in weeks 4–6") is done early, for local scope.
