---
id: ADR-20261119-6b2e
title: The plugin installs on Claude Code versions without --json, and doctor reports a failed install
status: ACCEPTED
date: 2026-11-19
scopes: ["seamspec/installers/claude_plugin.py", "seamspec/cli.py", "seamspec/core/doctor.py"]
invariants: []
supersedes: null
superseded_by: null
---

# The plugin installs on Claude Code versions without --json, and doctor reports a failed install

## Context

Setting up the company demo on the owner's work laptop (Claude Code 2.1.153, SeamSpec 0.1.1 from PyPI), `seamspec init --plugin` failed: `claude plugin marketplace add … --json` answered `error: unknown option '--json'`. SeamSpec adds `--json` to every `claude plugin` command to read a reliable result line; that option arrived in a later Claude Code (2.1.296 on the owner's other laptop documents it). The same two commands without `--json` installed the plugin fine. `claude plugin list --json` works on 2.1.153.

Worse, `seamspec doctor` then showed `✓ claude plugin`: its check only notices an install that is behind the installed SeamSpec, not one that is missing. The plugin was off and nothing said so.

## Decision

- **Retry without `--json`.** When a `claude plugin` command fails with "unknown option '--json'", SeamSpec runs it again without the option. Plain output has no result line to trust, so after such a run `enable()` reports `installed` only if `claude plugin list --json` shows the plugin enabled for this repository; otherwise `failed`, saying so. Upgrades already confirmed their result through the list (ADR-20261105-bf19).
- **Say how to finish by hand.** When the install fails, `init` prints the two commands without `--json`, to run in the repository folder.
- **Remember a failed install for `doctor`.** `init` records it in `.seamspec/.local/plugin_install.json` (this machine only) and deletes the record when an install or upgrade works. While the record exists and `claude plugin list` doesn't show the plugin enabled here, `doctor` warns with the message and the commands. Installing by hand silences it without rerunning `init`.

Alternatives: detecting the Claude Code version and choosing the options up front, rejected because version numbers don't say which subcommand gained `--json`, while the error does; warning in `doctor` whenever a repository has SeamSpec but no plugin, rejected because many people don't use Claude Code, and `init --no-plugin` is a valid choice.

## Enforced Invariants

None new.

## Consequences

- `seamspec init --plugin` works on older Claude Code versions that have `claude plugin list --json`.
- A repository that never asked for the plugin, or a machine without Claude Code, gets no new warning.
- An even older Claude Code without `claude plugin list --json` gets `failed` with the manual commands, never a false `installed`.
