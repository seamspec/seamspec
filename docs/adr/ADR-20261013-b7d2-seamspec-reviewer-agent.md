---
id: ADR-20261013-b7d2
title: SeamSpec's reviewer, a separate read-only agent that explains what waits for review
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-13
scopes: ["seamspec/templates/agents/reviewer.md", "seamspec/templates/commands/explain.md", "seamspec/brief.py", "seamspec/mcp_server.py", "seamspec/core/commands.py", "seamspec/templates/directive.md"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261013-b7d2: SeamSpec's reviewer, a separate read-only agent that explains what waits for review

## Context

Every rule SeamSpec enforces was approved by a person in `seamspec review`. That approval is only worth something if the person understands what they approve, and many of SeamSpec's users don't read tests.

In dogfooding the owner solved this by hand: they pasted each review screen into a second agent, which explained the rule, said what the test didn't cover, and gave a recommendation. The owner relied on it for every decision. Two things made it useful: plain language, and a reader that hadn't written the code (the agent that writes a test is a poor judge of it).

On 2026-10-13 the owner asked for this in the product: "a very protected agent with a tight system prompt" that explains the rule and the changes, while the user decides. It is item 4 of ADR-20261013-f4a8.

Constraints that shape it:
- SeamSpec's core calls no model (§3).
- Locked rule `inv_aa498871`: the agent never supplies the text of approval dialogs.
- Claude Code plugins can ship agents. Their `tools` field is an allowlist, a fresh context is the default, and `hooks`, `mcpServers` and `permissionMode` are ignored for plugin agents. Bash can't be limited to particular commands in an agent's definition.

## Decision

1. **A plugin agent, `seamspec:reviewer`**, generated from `seamspec/templates/agents/reviewer.md` into `seamspec-plugin/agents/reviewer.md` (same generator and staleness test as the skills).
   - **Tools, as an allowlist:** `Read`, `Grep`, `Glob`, and `review_material`. No Bash (it can't be narrowed), no Edit or Write, no other SeamSpec tool. It can read and explain; it can't change, run or approve anything.
   - **Fresh context, without the project's `CLAUDE.md`** (`omitClaudeMd: true`): it starts from SeamSpec's material and the files, not from the working agent's story. It can still Read `CLAUDE.md` if it needs the project's conventions.
   - **A tight prompt:** what it may and must not do; everything it reads is material, never instructions, and text addressing it is a red flag; a fixed answer per item (what it promises, what the test checks, what it doesn't check, what changed, what to look at, and "my read": looks sound / ask for changes / can't tell); and a closing line that this is an explanation, not a decision.
2. **A read-only tool, `review_material(ids?)`** (`seamspec/brief.py`): what `seamspec review` would show now, in its order (a supersede request with its replacement as one item), SeamSpec's own facts about each test (§15.1), and the code changes in each item's scope since the last commit (a bounded `git diff`, new files by name). It runs no test and changes no state. It gives the reviewer "what changed" without a shell and without relying on the agent that made the change.
3. **A command, `/seamspec:explain [ids]`.** The working agent launches the reviewer with a fixed one-line task and the ids only, shows the answer in full and unchanged under a line saying it comes from a separate agent, may add its own view only after it and marked as its own, and then offers to open `seamspec review`. If it can't launch the reviewer, it says so instead of writing an explanation itself.
4. **The protocol offers it** (§18 rule 6), and so do the `lock` and `supersede` skills, before they offer the review.
5. **The decision stays in `seamspec review`.** It keeps showing SeamSpec's own facts, the full test and red-green. The reviewer's words never enter SeamSpec's cards or dialogs.

**Alternatives considered:**
- **Put the explanation inside `seamspec review`.** It would mean a model in SeamSpec's core and a model's words at the point of decision, and it would break `inv_aa498871`'s intent.
- **Let the working agent explain.** It wrote the code and the test; the point is a reader who didn't.
- **Give the reviewer Bash for `git diff`.** Bash can't be narrowed in an agent definition, so "read-only" would rest on the prompt alone. The tool gives it the diff instead.
- **No verdict, only explanation.** The owner found the recommendation the most useful part. It stays, as "my read" with a reason, next to a reminder that the decision is theirs, and the full test stays on screen in the review.
- **A separate session (`claude --agent seamspec:reviewer`) instead of a subagent.** It removes the working agent from between reviewer and person, but asks the user to open another session for every review. It works today for anyone who wants it; the command is the everyday path.

## Limits

- **The working agent relays the answer.** It is told to show it unchanged, and Claude Code also shows the subagent's own transcript, but an agent could misreport. The threat this answers is an author grading its own work, not a hostile agent; a hostile agent could equally misdescribe a rule in chat today.
- **The reviewer can be wrong, and persuasive.** That is why the decision stays in a screen that shows the real test and can run it.
- **It reads text written by another agent,** and could be misled by it. It can't act on anything, so the worst case is a bad explanation.
- **Cost:** one subagent run per explanation, on the user's own Claude Code account.
- **Not yet checked in a real session.** The definition validates (`claude plugin validate`), and the tests check the allowlist, the prompt's guards, the material and the command; the first real run is the owner's.

## Enforced Invariants

To be proposed: "the reviewer agent's tools are read-only", and "`review_material` never runs a test or changes review state".

## Consequences

- Seven MCP tools in v0.1, about 1,300 of the 1,500-token budget for their definitions.
- A new plugin folder, `agents/`; seven skills.
- The directive changes (rule 6), so existing projects see a `doctor` note until they rerun `seamspec init`; `init` keeps any line a user wrote inside the block (ADR-20261011-b1c8).
- Cursor, VS Code and Antigravity get a reviewer only if and when their agent features allow a read-only agent; until then they get the review itself.
