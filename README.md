# SeamSpec

**Your AI agent can't quietly renegotiate what your team agreed.**

When you tell your coding agent *"totals must never go negative"* or *"we tried a thread pool; it deadlocked"*, that agreement usually lives in one chat and is gone by the next session. SeamSpec turns it into a **rule with a test**:
- **it's captured** from what you said, so nobody writes it by hand;
- **it's approved** by you;
- **it's enforced** when the agent finishes a task, before every commit, and in CI.

From then on, a change that breaks it is stopped, whoever makes it. Changing the rule itself takes your approval.

> **Status:** v0.1, the first release. It works with Claude Code, Cursor, VS Code (Copilot) and Antigravity, for projects tested with pytest or vitest.

## What it looks like

```text
You:    Other services call enqueue(payload, *, job_id=None, max_attempts=5); keep that working.
        And a retry must never wait more than 30 seconds.
Agent:  Done. I also proposed both as SeamSpec rules, each with a test.

$ seamspec review          ← you read each rule and its test, and approve
  ✔ inv_846cd96d · A retry never waits more than 30 seconds   (fails without your change: YES)

… next week, a new session …
You:    Our upstream is flaky; make retries more patient.
Agent:  The obvious change conflicts with a rule your team locked (inv_846cd96d: retries
        wait at most 30 s). I haven't changed it. Do you want to keep it, or replace the rule?
```

If an agent or a person changes the code anyway:
- **when the agent finishes:** SeamSpec's end-of-task check fails and sends the agent back with the rule and the failing line;
- **at commit:** the commit is refused;
- **in CI:** the build fails.

To change the rule, the agent files a *supersede request* and you approve it in `seamspec review`.

## What the benchmarks show

We tested SeamSpec against simpler setups on three small projects, with agreements the later requests tempt the agent to break. Plans and pass bars were fixed before each run, and the results include the ties. Model: Claude Sonnet 5.5.

| Question | Result |
|---|---|
| Agreements only said in chat, nobody writes them down: do they hold three sessions later? | Broken: **SeamSpec 0**, an agent keeping its own notes 8, nothing 22 (15 runs each). SeamSpec captured **39 of 40** agreements as tested rules. ([capture-1](https://github.com/seamspec/seamspec/blob/main/docs/benchmark/capture-1.md)) |
| A teammate's agent, in a fresh clone, makes the tempting changes: what reaches `main`? | Landed past CI: **SeamSpec 0**, the agent's notes 6, nothing 12. SeamSpec's teammate's agent broke 2, and CI stopped both. ([second-1](https://github.com/seamspec/seamspec/blob/main/docs/benchmark/second-1.md)) |
| Does the agent rewrite the checks instead of the code? | With plain tests and a Stop hook, it rewrote the rule tests 12 times. SeamSpec's locked tests stayed as approved. ([full-1](https://github.com/seamspec/seamspec/blob/main/docs/benchmark/full-1.md)) |

**Where SeamSpec does *not* win, so you can judge for yourself:**
- **Notes a person wrote carefully in `CLAUDE.md`** broke 0 too. A careful agent respects a good notes file. SeamSpec's difference is that its rules are tests, captured for you, enforced at commit and in CI, and changed only with your approval.
- **Within one long session,** nothing slipped in any setup ([long-1](https://github.com/seamspec/seamspec/blob/main/docs/benchmark/long-1.md)). Agents lose agreements **between** sessions.
- **The guard can be stricter than you meant.** In 2 of 9 runs, CI blocked a change that broke nothing the benchmark checked, because a captured rule pinned a detail you had stated. You then approve a replacement rule.

All the plans, results and allowed claims are in [the decision records](https://github.com/seamspec/seamspec/blob/main/docs/adr/README.md) (ADR-20261018-a4c2, ADR-20261019-c71d).

## Quick start

**You need:**
- Python 3.11+, [uv](https://docs.astral.sh/uv/) and git;
- a project tested with pytest or vitest;
- one of Claude Code, Cursor, VS Code (Copilot) or Antigravity.

The full walkthrough, from install to a team setup with CI, is **[Getting started](https://github.com/seamspec/seamspec/blob/main/docs/getting-started.md)**.

Install the `seamspec` command:

```bash
uv tool install seamspec
```

To upgrade later, run `uv tool upgrade seamspec`.

Then, in your project:

```bash
seamspec init
```

`init` asks before it changes anything outside your project. It:
- sets up the rule ledger (`.seamspec/`);
- adds a short protocol to `CLAUDE.md` / `AGENTS.md` that tells the agent when to propose rules;
- installs the git pre-commit check, and offers the Claude Code plugin and a CI workflow;
- with `--hosts cursor,vscode,antigravity`, sets up those editors too.

Some editors need a one-time click; see [docs/editors.md](https://github.com/seamspec/seamspec/blob/main/docs/editors.md).

Then just work. Say what must stay true, or tell the agent what failed before. When rules are waiting, run:

```bash
seamspec review
```

## For teams

The guard that matters for a team is **CI**: it runs every approved rule on each pull request, whoever wrote the change. Three steps:
1. Commit `.seamspec/` with your code, and add the workflow with `seamspec init --ci`.
2. On GitHub, make the **`seamspec / verify`** check required for `main` (branch protection).
3. Each teammate runs `seamspec init` after cloning. A clone doesn't carry anyone's local hooks or consent, and `init` shows what would run and asks first.

**Use it with your notes, not instead of them.** A good `CLAUDE.md` helps every agent understand the project. SeamSpec is for the few agreements that would really hurt if broken (money, data contracts, public APIs, security behaviour), so that they're tested, approved, and can't change without someone saying yes. Details: [Getting started, section 6](https://github.com/seamspec/seamspec/blob/main/docs/getting-started.md#6-for-teams).

## How it works

- **Rules are tests.** Each rule is a plain sentence plus a focused test, stored in `.seamspec/` and committed with your code. Approving one locks it by hash, so an agent can't quietly edit, skip or empty it.
- **Captured, then approved.** The agent proposes rules from what you say and from what it builds, and logs approaches that failed ("dead ends"). Nothing is enforced until you approve it.
  - `seamspec review` shows each test in full, and checks that it **fails without the change**.
  - `/seamspec:explain` has a separate, read-only reviewer agent explain each item in plain words before you decide.
- **Enforced in three places:**
  - **when the agent finishes a task** (a hook in your editor);
  - **before every commit** (it tests exactly what the commit records);
  - **in CI** (`seamspec verify --all --ci`).
- **Changed on purpose.** A requirement that really changed goes through a supersede request you approve. The old rule is retired, never deleted, and the history stays in git.
- **Your notes count too.** Jot anything in `BRAINDUMP.md`; the agent sorts it into proposed rules, decisions, dead ends or ideas. Rules whose code doesn't exist yet are kept as *planned* and shown to the agent until they can be tested.
- **Model-free.** SeamSpec itself never calls an AI model. It's a command-line tool, hooks and an MCP server, and everything lives in your git repository.

## Everyday commands

| | |
|---|---|
| `seamspec review` | Approve or reject what's waiting: rules, decisions, supersede requests, dead ends |
| `seamspec status` | Rules in force, what's waiting, and how often SeamSpec caught something |
| `seamspec verify` | Run every locked rule now |
| `seamspec spec` | The spec your code has earned: every approved rule, generated from the ledger |
| `seamspec drain` | List the BRAINDUMP notes not sorted yet |
| `seamspec doctor` | Check the setup |

**In the agent:**
- `/seamspec:lock` to protect a behaviour;
- `/seamspec:dead-end` to record what failed;
- `/seamspec:supersede` to replace a rule;
- `/seamspec:explain`, `/seamspec:drain`, `/seamspec:status`.

In Cursor, VS Code and Antigravity they are `/seamspec-lock` and so on. You can also just say it in plain words ("protect this", "that didn't work").

## Docs

- [Getting started](https://github.com/seamspec/seamspec/blob/main/docs/getting-started.md): install, first rules, the first week, team setup, troubleshooting
- [Setting it up in your editor](https://github.com/seamspec/seamspec/blob/main/docs/editors.md)
- [Design spec](https://github.com/seamspec/seamspec/blob/main/docs/SPEC.md): the full design, kept in step with the code
- [Decision records](https://github.com/seamspec/seamspec/blob/main/docs/adr/README.md): why it works the way it does, including every benchmark plan and result
- [Progress](https://github.com/seamspec/seamspec/blob/main/docs/PROGRESS.md)

## Contributing

Issues and pull requests are welcome: see [CONTRIBUTING.md](https://github.com/seamspec/seamspec/blob/main/CONTRIBUTING.md). To report a security problem privately, see [SECURITY.md](https://github.com/seamspec/seamspec/blob/main/SECURITY.md).

## License

[Apache-2.0](https://github.com/seamspec/seamspec/blob/main/LICENSE)
