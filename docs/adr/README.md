# Architecture Decision Records

Decisions that **change or add to** [`docs/SPEC.md`](../SPEC.md) are recorded here. Plain implementation detail doesn't need an ADR.

Decisions made before the build started (up to 2026-10-05) are in SPEC §26 "Resolved Decisions".

## When to write one

| Change | ADR? |
|---|---|
| Behavior, format, CLI/MCP surface, config key, schema or default differs from SPEC | **Yes**, and update SPEC in the same commit |
| Something new that SPEC doesn't cover | **Yes**, and add it to SPEC |
| A SPEC item moves between v0.1 / v0.2 / Later | **Yes** |
| A change to the build process (how we track work, review, release) | **Yes** |
| Internal refactor, naming inside a module, test layout, bug fix that matches SPEC | No |

## Format

Same as SeamSpec's own ADRs (SPEC §10.3), so these can move into `.seamspec/adrs/` in week 3 without conversion.

- **File name:** `ADR-YYYYMMDD-xxxx-short-slug.md`, where `xxxx` is 4 random hex characters (`python3 -c "import secrets; print(secrets.token_hex(2))"`).
- **Frontmatter:** `id`, `title`, `status` (`PROPOSED | ACCEPTED | SUPERSEDED | REJECTED`), `date`, `scopes`, `invariants`, `supersedes`, `superseded_by`.
- **Sections:** Context, Decision (include alternatives considered), Enforced Invariants, Consequences.
- To replace a decision, write a new ADR with `supersedes:` set, and set `status: SUPERSEDED` + `superseded_by:` on the old one. Never delete an ADR.

## Index

| ID | Title | Status |
|---|---|---|
| [ADR-20261005-ae6e](ADR-20261005-ae6e-build-directly-dogfood-from-week-3.md) | Build SeamSpec directly from SPEC.md; dogfood from week 3 | ACCEPTED |
| [ADR-20261005-c41d](ADR-20261005-c41d-v01-consistency-fixes.md) | Resolve v0.1 spec inconsistencies before week 1 | ACCEPTED |
| [ADR-20261005-2565](ADR-20261005-2565-committed-progress-log.md) | Track progress in a committed PROGRESS.md, with CLAUDE.md as the agent entry point | ACCEPTED |
| [ADR-20261005-6f2a](ADR-20261005-6f2a-week1-implementation-decisions.md) | Week 1 implementation decisions (schemas, config strictness, store, context, spec listings) | ACCEPTED |
| [ADR-20261005-d8bc](ADR-20261005-d8bc-branches-and-prs.md) | All changes land through branches and pull requests | ACCEPTED |
| [ADR-20261005-4b1e](ADR-20261005-4b1e-verifier-findings.md) | Verifier fixes found by running real pytest and vitest | ACCEPTED |
| [ADR-20261005-9c1a](ADR-20261005-9c1a-lifecycle-and-journal.md) | Lifecycle implementation; journal flags moves back to PROPOSED | ACCEPTED |
| [ADR-20261005-8e80](ADR-20261005-8e80-verify-trust-pre-commit.md) | verify CLI, consent and trust, pre-commit gate | ACCEPTED |
| [ADR-20261005-3adc](ADR-20261005-3adc-publishing-needs-owner-go.md) | Publishing to PyPI or npm needs the owner's explicit go-ahead | ACCEPTED |
| [ADR-20261005-b7e2](ADR-20261005-b7e2-review-and-red-green.md) | seamspec review, red-green check, and explicit runner-config confirmation | ACCEPTED |
| [ADR-20261005-c076](ADR-20261005-c076-request-copilot-review.md) | The agent requests a Copilot review on every PR it opens | ACCEPTED |
| [ADR-20261005-5009](ADR-20261005-5009-claude-code-hooks.md) | Claude Code hook adapter, aligned with the current hooks reference | ACCEPTED |
| [ADR-20261005-cc29](ADR-20261005-cc29-mcp-server.md) | MCP server on the MCP Python SDK 2.x | ACCEPTED |
| [ADR-20261005-5675](ADR-20261005-5675-claude-code-plugin.md) | Claude Code plugin, verified in real sessions | ACCEPTED |
| [ADR-20261005-9b8f](ADR-20261005-9b8f-setup-friction-runners-and-clones.md) | Less setup friction: project tools without activation, one question on a fresh clone | ACCEPTED |
| [ADR-20261005-428a](ADR-20261005-428a-plugin-install-from-init.md) | seamspec init installs the Claude Code plugin at local scope, after asking | ACCEPTED |
| [ADR-20261006-c300](ADR-20261006-c300-chat-approvals-design.md) | Approvals in chat through an MCP form dialog, with hook guards (design) | ACCEPTED |
| [ADR-20261006-0f6e](ADR-20261006-0f6e-dogfooding-seamspec-on-itself.md) | Dogfooding - SeamSpec governs its own repo; docs/adr stays until agents have an ADR tool | ACCEPTED |
| [ADR-20261006-c8b9](ADR-20261006-c8b9-rough-benchmark-plan-and-pass-bar.md) | Rough benchmark - design, pass bar fixed before running, and cost | ACCEPTED |
| [ADR-20261006-b270](ADR-20261006-b270-rough-benchmark-result-pass.md) | Rough benchmark result - PASS; keep building, lead with remembered agreements | ACCEPTED |
| [ADR-20261006-9623](ADR-20261006-9623-doctor-v01.md) | seamspec doctor in v0.1 - what it checks, the CI base branch, and what waits | ACCEPTED |
| [ADR-20261006-d16b](ADR-20261006-d16b-ci-workflow-from-init.md) | The CI workflow and CODEOWNERS that init installs | ACCEPTED |
| [ADR-20261007-8663](ADR-20261007-8663-remaining-skills-v01.md) | The remaining v0.1 skills - supersede, checkpoint, context, status | ACCEPTED |
| [ADR-20261007-1b4c](ADR-20261007-1b4c-mode-changes.md) | Changing the mode after init - keep by default, raise with consent, lower only by a human | ACCEPTED |
| [ADR-20261007-d757](ADR-20261007-d757-trim-ci-minutes.md) | Trim SeamSpec's own CI to fit the Actions minutes of a private repo | ACCEPTED |
| [ADR-20261007-e1a7](ADR-20261007-e1a7-quick-condition-e.md) | Quick condition E - rules written in CLAUDE.md, and how its result is read (fixed before running) | ACCEPTED |
| [ADR-20261007-ac04](ADR-20261007-ac04-ledger-single-source-session-start-hook.md) | The ledger stays the single source; a session-start hook adds the current rules (no notes files) | ACCEPTED |
| [ADR-20261008-5d1e](ADR-20261008-5d1e-chat-approvals-off-by-default.md) | Chat approvals off by default until Claude Code shows the whole dialog (verification 2) | ACCEPTED |
| [ADR-20261011-8013](ADR-20261011-8013-readable-review.md) | A readable review - summary first, the test's checks pulled out, the full test still shown | ACCEPTED |
| [ADR-20261011-0995](ADR-20261011-0995-generated-spec-and-positioning.md) | A spec generated from the ledger; positioning and order of work after dogfooding | ACCEPTED |
| [ADR-20261011-3c7e](ADR-20261011-3c7e-redgreen-editable-installs.md) | Red-green points the HEAD run at HEAD's code when the project is installed in editable mode | ACCEPTED |
| [ADR-20261011-6b2d](ADR-20261011-6b2d-session-summary-keeps-reasons.md) | The session-start summary keeps each dead end's reason, shrinks in smaller steps, and may use 8,000 characters | ACCEPTED |
| [ADR-20261011-d4a1](ADR-20261011-d4a1-mcp-server-finds-the-moved-session.md) | The MCP server finds the project of a session that was moved to another folder | ACCEPTED |
| [ADR-20261011-e7c5](ADR-20261011-e7c5-layout-aware-hints.md) | Runner hints fit the project - how to import its code, and which program a runner resolves to | ACCEPTED |
| [ADR-20261011-a9f3](ADR-20261011-a9f3-ci-workflow-install-source.md) | The CI workflow installs the SeamSpec version that wrote it; an unreleased build doesn't offer the workflow | ACCEPTED |
| [ADR-20261011-b1c8](ADR-20261011-b1c8-init-keeps-lines-inside-its-block.md) | `seamspec init` keeps lines someone else wrote inside its CLAUDE.md block | ACCEPTED |
| [ADR-20261013-7c2e](ADR-20261013-7c2e-supersede-locks-replacement-first.md) | A rule is retired only after its replacement is locked; the review decides both as one | ACCEPTED |
| [ADR-20261013-4e9b](ADR-20261013-4e9b-readable-failure-message.md) | When a rule fails, say which rule and which check, before any test output | ACCEPTED |
| [ADR-20261013-a5d3](ADR-20261013-a5d3-redgreen-says-when-code-is-new.md) | Red-green says when a "yes" only means the code is new | ACCEPTED |
| [ADR-20261013-2f6b](ADR-20261013-2f6b-generated-spec-as-built.md) | `seamspec spec` as built: only approved rules, same bytes from the same ledger | ACCEPTED |
| [ADR-20261013-c3f7](ADR-20261013-c3f7-approved-rule-tests-are-not-linted.md) | Approved rule tests are not linted or reformatted | ACCEPTED |
| [ADR-20261013-9d41](ADR-20261013-9d41-full-benchmark-plan-and-pass-bar.md) | Full benchmark: plan and pass bar, fixed before the run | ACCEPTED |
| [ADR-20261013-e2b6](ADR-20261013-e2b6-full-benchmark-result.md) | Full benchmark result: pass; what we claim, and what we don't | ACCEPTED |
| [ADR-20261013-f4a8](ADR-20261013-f4a8-v01-scope-after-the-benchmark.md) | v0.1 after the benchmark: BRAINDUMP, critical rules, three more hosts, and an explainer for reviews | ACCEPTED |
| [ADR-20261013-b7d2](ADR-20261013-b7d2-seamspec-reviewer-agent.md) | SeamSpec's reviewer, a separate read-only agent that explains what waits for review | ACCEPTED |
| [ADR-20261013-c1a9](ADR-20261013-c1a9-critical-rules.md) | Critical rules: a few rules the agent always sees in full | ACCEPTED |
| [ADR-20261013-d9e4](ADR-20261013-d9e4-braindump-in-v01.md) | BRAINDUMP in v0.1, as designed in §13, with five changes | ACCEPTED |
| [ADR-20261013-e8f3](ADR-20261013-e8f3-cursor-vscode-antigravity.md) | Cursor, VS Code and Antigravity in v0.1: rules, tools, session-start and stop hooks | ACCEPTED |
| [ADR-20261014-3b1e](ADR-20261014-3b1e-commit-check-tests-staged-files.md) | The commit check tests what the commit records, not the files on disk | ACCEPTED |
| [ADR-20261014-6c2d](ADR-20261014-6c2d-antigravity-hands-on-fixes.md) | Fixes from the Antigravity hands-on test: project folder for the server, tool fallbacks, drain --dismiss | ACCEPTED |
| [ADR-20261014-8a57](ADR-20261014-8a57-braindump-sorting-limits.md) | BRAINDUMP sorting: decisions count toward the review cap, reject the rest at once, offer again when the code changes | ACCEPTED |
| [ADR-20261014-5e3a](ADR-20261014-5e3a-planned-rules.md) | Planned rules: notes whose code doesn't exist yet steer the agent until they can be proposed | ACCEPTED |
| [ADR-20261015-4f7b](ADR-20261015-4f7b-reviewer-in-vscode-and-antigravity.md) | SeamSpec's reviewer in VS Code and Antigravity, as each tool's own read-only agent | ACCEPTED |
| [ADR-20261015-c8e1](ADR-20261015-c8e1-capture-and-long-session-benchmarks.md) | Plan and pass bars for the capture and long-session benchmarks | ACCEPTED |
| [ADR-20261016-2d9a](ADR-20261016-2d9a-vscode-copilot-agent-hooks.md) | VS Code hands-on: one hook file for VS Code's Local and Copilot agents, and setup notes | ACCEPTED |
| [ADR-20261017-7b0e](ADR-20261017-7b0e-init-rerun-keeps-consent.md) | Rerunning init keeps an earlier yes to automatic test runs | ACCEPTED |
| [ADR-20261017-1f5c](ADR-20261017-1f5c-cursor-hands-on.md) | Cursor hands-on: hooks work as built; init says to switch the server on | ACCEPTED |
| [ADR-20261018-9c4d](ADR-20261018-9c4d-cursor-reviewer-and-setup-guide.md) | Cursor gets the reviewer; the agent says when SeamSpec's tools are off; a setup guide per editor | ACCEPTED |
| [ADR-20261018-6e1a](ADR-20261018-6e1a-capture-what-the-user-states.md) | Calibration fixes: capture what the user states, record each catch, count cost per prompt | ACCEPTED |
| [ADR-20261018-0b7d](ADR-20261018-0b7d-pytest-pythonpath-carried-over.md) | SeamSpec's pytest.ini carries over the project's own pytest pythonpath | ACCEPTED |
| [ADR-20261018-a4c2](ADR-20261018-a4c2-capture-and-long-session-results.md) | Results: capture passes, the long session showed no slip | ACCEPTED |
| [ADR-20261019-5f3b](ADR-20261019-5f3b-second-actor-benchmark-plan.md) | Plan and pass bar for the second-actor benchmark | ACCEPTED |
| [ADR-20261019-c71d](ADR-20261019-c71d-second-actor-results.md) | Result: with SeamSpec, nothing broken reached main, whoever made the change | ACCEPTED |
| [ADR-20261019-e2f8](ADR-20261019-e2f8-verify-in-a-clone-never-set-up.md) | `seamspec verify` in a clone never set up on this machine says to run `seamspec init` | ACCEPTED |
| [ADR-20261023-7d41](ADR-20261023-7d41-plugin-from-github-at-the-release-tag.md) | A released SeamSpec takes the Claude Code plugin from GitHub at its own tag; project scope for teams | ACCEPTED |
| [ADR-20261024-b3e9](ADR-20261024-b3e9-release-rehearsal-findings.md) | Release rehearsal findings - licence in the packages, notes below the BRAINDUMP marker pointed out | ACCEPTED |
