# Changelog

All notable changes to SeamSpec are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Before 1.0, a minor version (0.2, 0.3) may change how things work; the changelog says when it does.

## [0.1.0] - Unreleased

The first release. The date is set when it is published.

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
