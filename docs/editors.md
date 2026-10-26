# Setting SeamSpec up in your editor

Run `seamspec init` in your project. It asks before changing anything outside the project. For Cursor, VS Code or Antigravity, add `--hosts cursor`, `--hosts vscode` or `--hosts antigravity` (several, comma-separated). If the editor's folder (`.cursor`, `.vscode`, `.agents`) already exists, plain `seamspec init` asks about it.

Some editors then need a click or two of your own. That's on purpose: these editors don't let a project start programs until you allow it, and SeamSpec doesn't get around that.

## At a glance

| | What you do once | What works then |
|---|---|---|
| **Claude Code** | Say yes when `init` offers the plugin | Everything |
| **Antigravity** | Nothing. If the project was already open, restart the `seamspec` server in its MCP settings or reload the window | Everything except the rules shown at the moment of an edit |
| **Cursor** | Switch the `seamspec` server on: Cursor Settings → MCP (or Tools) | Everything except the rules shown at the moment of an edit |
| **VS Code (Copilot)** | Start the `seamspec` server: Command Palette → `MCP: List Servers` → seamspec → Start. On Copilot Business or Enterprise, an org admin first enables two Copilot policies (below) | Everything except the rules shown at the moment of an edit |

**"Everything" means:**
- **Before editing:** SeamSpec's tools (the rules for a file, proposing a rule, logging a dead end); the rules and dead ends at the start of every chat; the agent's commands (`/seamspec-lock`, `/seamspec-drain`, …); the read-only reviewer (`/seamspec-explain`).
- **Enforcement:** the check when the agent finishes a task (a broken rule sends it back to fix it or ask); the check before every commit; CI.

The commit check and CI are plain git, so they work whatever editor or agent you use.

## If you skip the one-time step

The rules still hold:
- The start-of-chat summary, the end-of-task check and the commit check don't need the server.
- The agent is told to use SeamSpec's terminal commands (`seamspec context <file>`, `seamspec propose`, …) when its tools are missing, and to tell you once how to turn them on.

You lose convenience, not protection.

## Claude Code

`seamspec init` offers to install SeamSpec's Claude Code plugin for this project only (local scope). A released SeamSpec also asks whether to turn it on for everyone in the repository: it then goes into `.claude/settings.json`, which you commit, and each teammate's Claude Code offers it once they trust the folder. The plugin brings the hooks, the tools and the `/seamspec:*` commands. Nothing else to do.

## Antigravity

`seamspec init --hosts antigravity` writes:
- `AGENTS.md` (the rules for the agent);
- `.agents/mcp_config.json` (SeamSpec's tools, with this project's path, because Antigravity starts servers outside the project);
- `.agents/hooks.json`;
- `.agents/skills/seamspec-*`;
- `.agents/agents/seamspec-reviewer.md`.

Antigravity loads them by itself.

- **After re-creating the folder or rerunning `init`:** restart the `seamspec` server in Antigravity's MCP settings, or reload the window.
- **In a clone elsewhere:** the saved path points at the old folder. Rerun `seamspec init --hosts antigravity`; `seamspec doctor` warns about it.

## Cursor

`seamspec init --hosts cursor` writes:
- `AGENTS.md`;
- `.cursor/mcp.json`;
- `.cursor/hooks.json`;
- `.cursor/commands/seamspec-*.md`;
- `.cursor/agents/seamspec-reviewer.md`.

Then:
1. **Hooks:** nothing to do. Cursor runs them by itself.
2. **Tools:** open Cursor Settings → MCP (or Tools; Cmd+Shift+P → "MCP" finds it) and switch **seamspec** on. It should show 9 tools.
3. **The reviewer:** `/seamspec-explain`, or type `/seamspec-reviewer` yourself.

## VS Code (Copilot)

`seamspec init --hosts vscode` writes:
- `AGENTS.md`;
- `.vscode/mcp.json`;
- `.github/hooks/seamspec.json`;
- `.github/prompts/seamspec-*.prompt.md`;
- `.github/agents/seamspec-reviewer.agent.md`.

The hook file works in both of VS Code's agents, **Local** and **Copilot**, and in the Copilot CLI.

Then:
1. **Trust the folder** when VS Code asks. Hooks don't run in Restricted Mode.
2. **Start the server:** Command Palette → `MCP: List Servers` → seamspec → Start, and allow it.
3. **Copilot Business or Enterprise only:** an org admin enables two Copilot policies, under github.com → the organization → Settings → Copilot → Policies. Both are off by default; until then VS Code shows these settings as "Managed by organization".
   - **"Editor preview features"**, for hooks;
   - **"MCP servers in Copilot"**, for SeamSpec's tools.
4. **The reviewer:** `/seamspec-explain` runs in the `seamspec-reviewer` agent, which answers you directly.

**SeamSpec checks the saved files.** VS Code can hold an agent's edits in the editor until you click **Keep** (or save). Until then, SeamSpec's checks, the stop hook among them, see the file as it was. If the agent says it changed a file but SeamSpec still reports the old code, click Keep or save, then run `seamspec verify`.

## Not built yet

**Showing the rules for a file at the moment the agent edits it,** and blocking edits to SeamSpec's own files, exist only in Claude Code. The other editors haven't documented the names their hooks give to edit tools. Until then:
- the start-of-chat summary and the agent's own check before editing cover the rules;
- the commit check and CI catch edits to `.seamspec/`.
