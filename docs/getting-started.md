# Getting started with SeamSpec

This guide takes you from nothing to a project where the rules your team agreed on are tested, approved and enforced. It covers a solo project first, then what a team adds. Setup for each editor is in [editors.md](editors.md).

## 1. Before you start

- **Python 3.11 or newer** and **[uv](https://docs.astral.sh/uv/)**: they install and run the `seamspec` command.
- **git:** SeamSpec keeps its rules in your repository and checks commits.
- **A project tested with pytest (Python) or vitest (TypeScript/JavaScript).** Other runners (jest, go test, cargo) come later. A project with no tests yet is fine: SeamSpec writes its own rule tests.
- **One of these coding agents:** Claude Code, Cursor, VS Code with Copilot, or Antigravity.

## 2. Install

Until the first release, install from a clone of the SeamSpec repository:

```bash
git clone https://github.com/seamspec/seamspec.git && cd seamspec && uv tool install --force --editable .
```

Check it works:

```bash
seamspec --version
```

## 3. Set up your project

In your project's folder:

```bash
seamspec init
```

It asks a few questions. Nothing outside your project changes without a yes.

| Question | What to pick |
|---|---|
| Mode | **enforced** (the default offered). See [Modes](#7-modes) |
| Allow automatic test runs? | **Yes.** It lets SeamSpec run your approved rules when the agent finishes a task and before each commit. They run with your permissions, so it shows what would run and asks first |
| Install the Claude Code plugin? | **Yes** if you use Claude Code. It's only for Claude Code, and only for this project |
| Turn it on for everyone in this repository? (released versions only) | **Yes** for a team: it goes into `.claude/settings.json`, which you commit, and each teammate's Claude Code offers it. **No** keeps it to you |
| Add a CI workflow? | **Yes** for a team (see [section 6](#6-for-teams)) |

**What `init` writes:**
- `.seamspec/`: the rule ledger (rules, their tests, dead ends, decisions, settings);
- a short **SeamSpec block** in `CLAUDE.md` (and `AGENTS.md` for other editors): when to propose rules, what not to touch;
- a **git pre-commit hook** that runs your approved rules;
- **`BRAINDUMP.md`**: your scratchpad, git-ignored;
- with `--hosts cursor,vscode,antigravity`: those editors' settings, hooks and commands.

Then do the one-time step for your editor in [editors.md](editors.md), for example switching SeamSpec's server on in Cursor.

## 4. Your first rules

You don't write rules. You say what must stay true, and the agent proposes them:

> "Other services call `enqueue(payload, *, job_id=None, max_attempts=5)`, keep that working. And a retry must never wait more than 30 seconds."

> "We tried a thread pool here last month; it deadlocked."

**What the agent does:**
- **For an agreement:** it proposes a **rule**, a plain sentence plus a focused test, and runs the test.
- **For something that failed:** it logs a **dead end**, so later sessions don't retry it. Dead ends need no approval.
- **When the code doesn't exist yet:** it keeps the agreement as **planned** and proposes it once the code works.
- **BRAINDUMP notes:** anything you jot in `BRAINDUMP.md` gets sorted the same way when you say "sort my braindump".

**Then review.** Rules don't apply until you approve them. In a terminal (not the agent's own shell):

```bash
seamspec review
```

For each proposed rule, you see:
- the rule;
- its full test;
- what the test checks;
- whether it **fails without the change** (proof the test protects something real).

Answer `a` to approve, `r` to reject (optionally recording why as a dead end), `s` to skip, or `q` to stop. Before deciding, you can ask the agent for `/seamspec:explain`: a separate, read-only reviewer agent that didn't write the rules explains each one in plain words.

Approved rules are **locked**: their test can't be quietly edited, skipped or emptied.

## 5. Day to day

**When the agent wants to break a rule,** it should say so and ask, because the rules are shown to it at the start of each chat and before it edits. If it changes the code anyway:
- **when it finishes a task**, SeamSpec's check fails and sends it back with the rule and the failing line;
- **at commit**, the commit is refused. The check tests exactly what the commit records, not just the files on disk;
- **in CI**, the build fails (see section 6).

**When a requirement really changes,** the agent files a **supersede request**: the old rule, the reason, and usually a replacement rule. Approve it in `seamspec review`. The old rule is retired, never deleted, and the history stays in git.

**Useful commands:**

| | |
|---|---|
| `seamspec status` | Rules in force, what's waiting for review, and how often SeamSpec caught something |
| `seamspec verify` | Run every approved rule now |
| `seamspec spec` | Every approved rule as one readable document: the spec your code has earned |
| `seamspec drain` | BRAINDUMP notes not sorted yet, and planned rules |
| `seamspec critical <id>` | Mark a rule critical, so the agent always sees it in full |
| `seamspec doctor` | Check the setup |

**In the agent:** `/seamspec:lock`, `/seamspec:dead-end`, `/seamspec:supersede`, `/seamspec:explain`, `/seamspec:drain`, `/seamspec:status`. In other editors, they're `/seamspec-lock` and so on. Plain words work too: "protect this", "that didn't work", "sort my braindump".

## 6. For teams

A notes file guides whichever agent reads it. SeamSpec's rules are tests, and **CI runs them on every push**. That is what stops a broken agreement reaching `main`, whoever made the change: a teammate, their agent, another tool, or someone editing by hand. In our second-actor benchmark, broken agreements landed on `main` 6 times with the agent's own notes, 12 times with nothing, and 0 times with SeamSpec ([second-1](benchmark/second-1.md)).

**Set it up once, for the repository:**
1. **Commit `.seamspec/`** with your code. The rules, their tests and the decisions are shared files, reviewable in pull requests.
2. **Add the CI workflow:**
   ```bash
   seamspec init --ci
   ```
   It writes `.github/workflows/seamspec.yml`, which on every pull request:
   - runs `seamspec doctor --ci` (rules can't be quietly deleted or weakened);
   - runs `seamspec verify --all --ci` (every approved rule passes).

   Until SeamSpec's first release, the workflow installs it from its GitHub repository; edit that line if your CI can't reach it.
3. **Make the check required.** On GitHub: **Settings → Branches → Add branch protection rule** for `main`, then tick **Require status checks to pass** and choose **`seamspec / verify`**. Without this, CI reports a broken rule but doesn't stop the merge.
4. **Optional, `strict` mode:** `seamspec init --mode strict` also adds a block to `.github/CODEOWNERS` for `.seamspec/` and the rule tests. Two more steps make it count:
   - **Name your reviewers:** replace the placeholder `@your-team/leads` with real people or a team (`@maya`, `@acme/leads`) who have write access to the repository. Rerunning `init` keeps them. `seamspec doctor` warns while the placeholder is there.
   - **Require their review:** in the same branch protection rule, tick **Require a pull request before merging**, then **Require review from Code Owners**. Without it, GitHub only *suggests* the code owners as reviewers.

**Each teammate, after cloning:**

```bash
seamspec init
```

A clone doesn't carry anyone's local setup: the hooks, the consent for automatic runs and the editor plugin stay on each person's machine. `init` shows the test commands the repository would run and asks before trusting them. Until a teammate does this, their agent can still read the rules, but nothing checks locally. `seamspec verify` will say so, and CI still checks every push.

**Who approves?** Anyone who runs `seamspec review`. Approvals are recorded with the person's git identity. In `strict` mode, once you've named real reviewers and required code-owner reviews (step 4), CODEOWNERS makes sure the right people review changes to the rules before they merge.

**Keep your notes too.** A good `CLAUDE.md` still helps every agent understand the project. Agreements that can't be tested (style, architecture preferences) belong there, or as SeamSpec decisions. Use rules for the few agreements that would really hurt if broken: money, data contracts, public APIs, security behaviour.

## 7. Modes

| Mode | What runs | When to use it |
|---|---|---|
| `advisory` | Nothing automatic. The agent sees the rules and is asked to respect them | Trying SeamSpec out |
| `enforced` | The end-of-task check, the commit check, and CI if you add it | Most projects |
| `strict` | As enforced, plus CI always, and CODEOWNERS for the rules | Teams and important repositories |

To change mode, rerun `seamspec init --mode <mode>`. Lowering it needs you at a terminal; an agent can't do it.

## 8. When SeamSpec is stricter than you meant

A captured rule follows what was said. If you said `max_attempts=5`, the rule may pin that default, and a later change to it is blocked even if nobody minds. In our benchmark this happened in 2 of 9 runs. When it does:
- **the change is fine:** approve the agent's supersede request and replacement rule in `seamspec review`;
- **the rule is too strict from the start:** reject it at review, and ask the agent for a narrower one;
- **while reviewing:** watch for tests that check more than the sentence promises. `/seamspec:explain` points them out.

## 9. Troubleshooting

| You see | What to do |
|---|---|
| The agent says SeamSpec's tools are off | Switch the `seamspec` server on in your editor's MCP settings ([editors.md](editors.md)). The rules still hold meanwhile: the agent uses the `seamspec` commands |
| `seamspec verify`: "SeamSpec isn't set up for this clone on this machine" | Run `seamspec init` in that clone |
| `seamspec verify`: "This clone is not trusted" | The repository's test commands or locked tests changed since you trusted it. Run `seamspec trust`, which shows what changed and asks |
| VS Code shows hooks or MCP as "Managed by organization" | On Copilot Business or Enterprise, an org admin enables the Copilot policies "Editor preview features" and "MCP servers in Copilot" |
| Nothing happens when the agent finishes, in VS Code | Make sure the folder is trusted, and that your chat is a **Copilot** or **Local** agent session (both read `.github/hooks/seamspec.json`) |
| An editor still behaves as before setup | Restart the `seamspec` server in its MCP settings, or reload the window, and start a new chat |
| A commit is refused although your files look fine | The check tests what is **staged**. If you fixed something after `git add`, stage it again |
| `seamspec doctor` warns about `pythonpath` | Your pytest settings add a folder (e.g. `src`) that SeamSpec's `.seamspec/pytest.ini` doesn't. Add it there as `../src` and confirm the change in `seamspec review` |

## 10. Turning it off

- **Pause enforcement:** `seamspec init --mode advisory`. This removes SeamSpec's commit hook; the rules stay.
- **Remove the Claude Code plugin from a project:** `claude plugin uninstall seamspec@seamspec --scope local` (or `--scope project` if you turned it on for the team, then commit `.claude/settings.json`).
- **Remove it completely,** in this order:
  1. **Switch to advisory first:** `seamspec init --mode advisory`, while `.seamspec/` still exists. It removes the commit hook. Skipped, the hook stays and refuses the commit that removes SeamSpec. If a hook manager (pre-commit, Husky, Lefthook) runs SeamSpec instead, delete that step from its config.
  2. **Remove the plugin** (above), if you installed it.
  3. **Remove the required check:** if `seamspec / verify` is a required status check (section 6), untick it in the branch protection rule before you delete the workflow. Otherwise every pull request waits for a check that never runs.
  4. **Delete SeamSpec's files:** `.seamspec/`; `.github/workflows/seamspec.yml`; and the editor files only SeamSpec uses, all named `seamspec…`: the commands, prompts, skills and reviewer agents, and `.github/hooks/seamspec.json`.
  5. **Remove SeamSpec's parts of shared files,** keeping the rest:
     - the SeamSpec block in `CLAUDE.md` / `AGENTS.md`, between the `seamspec:begin` and `seamspec:end` markers, and in `strict` mode the one in `.github/CODEOWNERS`;
     - the `seamspec` server in `.cursor/mcp.json`, `.vscode/mcp.json` and `.agents/mcp_config.json`;
     - the hooks that run `seamspec` in `.cursor/hooks.json` and `.agents/hooks.json`;
     - SeamSpec's lines in `.gitignore`. If you keep `BRAINDUMP.md` (it's yours), keep its lines (for a file set in `braindump.path` or a link, the one for the file it points to as well), so your notes stay out of the commit.
  6. **Commit** the removal. Check `git status` first: nothing personal should be staged.
  7. **The command itself:** `uv tool uninstall seamspec`, once no project uses it.
