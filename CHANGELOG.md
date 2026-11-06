# Changelog

All notable changes to SeamSpec are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Before 1.0, a minor version (0.2, 0.3) may change how things work; the changelog says when it does.

## [Unreleased]

### Fixed
- **An error isn't reported as a regression.** When a rule's test stops with an error before or around its checks (a missing package, a broken import or fixture) and no check actually failed, `seamspec verify`, the commit check and the agent's stop message now say so, instead of "Fix the regression, or supersede the rule". The commit is still blocked.
- **The reviewer's verdict matches its own findings.** `/seamspec:explain` (and `/seamspec-explain`) could list real gaps in a rule and still end with "looks sound to approve". Its "My read" now says "ask for changes first", naming the change, whenever it found part of the promise untested, a test that would pass with the promise broken, or code that doesn't match the rule. Rerun `seamspec init --hosts ...` to update the reviewer in Antigravity, VS Code and Cursor.
- **A warning before a personal email goes into a rule.** Approving records your git identity in the rule, which is committed and can't be edited. When that identity uses a personal address (Gmail, Outlook, iCloud and similar), `init`, `seamspec review`, `seamspec approve` and the chat review now say so first, so you can switch to a noreply address.
- **Hand edits to a locked rule are caught locally.** The stop and commit checks and `seamspec doctor` now compare a locked rule's title, scope, test details and approval with the last commit, not just its status. Before, only CI caught them.
- **Antigravity is offered for a `GEMINI.md`.** `seamspec init` now offers to set up Antigravity when a project has a `GEMINI.md` but no `.agents` folder yet.
- **Antigravity's MCP config stays out of git.** `.agents/mcp_config.json` holds this machine's path, so `init` adds it to `.gitignore`. If it was already committed, `init` and `doctor` say to run `git rm --cached .agents/mcp_config.json`. After cloning, run `seamspec init --hosts antigravity`.
- **Upgrades reach the Claude Code plugin.** After `uv tool upgrade seamspec`, `seamspec init` offers to move the plugin to the new version's tag and update it (`--plugin` does it without asking), and `seamspec doctor` warns when the plugin doesn't match.

## [0.1.0] - 2026-10-27

The first release.

### Rules
- **Rules are tests.** Each rule is a plain sentence plus a focused pytest or vitest test, kept in `.seamspec/` and committed with your code. Approving one locks it by hash, so it can't be quietly edited, skipped or emptied.
- **Captured by the agent, approved by you.** The agent proposes rules from what you say and from what it builds (`propose_invariant`), and logs approaches that failed (`log_dead_end`) and decisions (`propose_decision`). Nothing is enforced until a person approves it.
- **`seamspec review`** shows each item with its test in full and checks that the test **fails without the change** (red-green), saying when a "yes" only means the code is new. `/seamspec:explain` has a separate, read-only reviewer agent explain each item first.
- **Changed on purpose:** a rule is replaced through a supersede request you approve; the replacement is locked before the old rule is retired, and nothing is deleted.

### Enforcement
- **When the agent finishes a task:** a stop hook runs the locked rules and sends the agent back with the failing rule and line.
- **Before every commit:** a git pre-commit check that tests exactly what the commit records (the staged files), with a short message naming each broken rule.
- **In CI:** `seamspec init --ci` adds a GitHub Actions workflow running `seamspec doctor --ci` and `seamspec verify --all --ci`.
- **Modes:** `advisory`, `enforced` (the default) and `strict` (adds a CODEOWNERS block; `init` keeps the reviewers you name).

### Agents and editors
- **Claude Code:** a plugin with the hooks, the MCP server and the `/seamspec:*` skills, from this repository at the release's tag; for you only, or for everyone in the repository (`--plugin-scope project`).
- **Cursor, VS Code (Copilot) and Antigravity:** `seamspec init --hosts cursor,vscode,antigravity` sets up their MCP server, hooks and commands.
- **The protocol** in `CLAUDE.md` / `AGENTS.md` tells the agent when to read rules, propose them and log dead ends; `init` keeps lines you wrote inside its block.
- **MCP tools:** `get_constraints`, `propose_invariant`, `log_dead_end`, `propose_decision`, `request_supersede`, `braindump_pending` and more.

### Notes and the spec
- **`BRAINDUMP.md`:** jot notes; the agent sorts them into proposed rules, decisions, dead ends or ideas (`/seamspec:drain`). Secrets are redacted from what it records. Rules whose code doesn't exist yet are kept as *planned* and shown to the agent.
- **`seamspec spec`:** one readable document of every approved rule, generated from the ledger; `--check` fails when a committed copy is out of date.

### Commands
`init`, `review`, `status`, `verify`, `context`, `drain`, `spec`, `doctor`, `trust`, `mcp`, and more; see `seamspec --help`.

### Known limits
- Test runners: pytest and vitest only.
- Tested on Linux and macOS, Python 3.11 to 3.14. Windows isn't tested.
- An upgrade doesn't yet move the Claude Code plugin to the new version's tag; that comes before 0.1.1.

[0.1.0]: https://github.com/seamspec/seamspec/releases/tag/v0.1.0
