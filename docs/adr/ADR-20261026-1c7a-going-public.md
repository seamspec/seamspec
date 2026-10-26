---
id: ADR-20261026-1c7a
title: Going public - history checked, contribution and security policy
status: ACCEPTED
date: 2026-10-26
scopes: ["CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md", ".github/ISSUE_TEMPLATE/", "README.md"]
invariants: []
supersedes: null
superseded_by: null
---

# Going public - history checked, contribution and security policy

## Context

Release step 3: the repository becomes public before the PyPI release, because the Claude Code plugin is fetched from it (ADR-20261023-7d41) and the README promises the benchmark evidence. Going public shows the whole history, every PR and issue, and every document.

## Decision

1. **History checked before going public (2026-10-26)**, across all 95 commits:
   - **Files ever committed:** no `.env`, key files, `notes/`, benchmark logs or results, or local settings.
   - **Every added line:** checked for Anthropic, OpenAI-style, GitHub, AWS, Slack, Google, PyPI and npm tokens, private keys, and secrets assigned in code. The only match is the made-up `AKIAABCDEFGHIJKLMNOP` in a redaction test.
   - **Email addresses:** only the owner's GitHub no-reply address and made-up `@example.com` ones.
   - **CI:** `tests.yml` runs on `pull_request` (not `pull_request_target`) with `contents: read` and no secrets, so pull requests from forks can't reach anything.
   - **Left as they are:** six of SeamSpec's own rule records name the owner's OS login as the approver. Records are never edited (§11), and the login is not sensitive.
2. **How people contribute** (`CONTRIBUTING.md`): set-up and checks from `CLAUDE.md`, a branch and PR with the template, the spec and §19 contracts kept in step, and an ADR for design changes. It also covers: generated files, no `ruff format` on `docs/`, a model-free core, and no code copied from other tools. Contributions are under Apache-2.0 by section 5 of the licence; there is no CLA. SeamSpec guards its own repository; a deliberate break is explained in the PR and a maintainer retires or replaces the rule.
3. **Security reports go through GitHub's private vulnerability reporting** (`SECURITY.md`), not email, so no personal address is published. It lists what counts (running code without consent, approving without a person, bypassing the guard, leaking secrets, the MCP server or hooks leaving their project) and what doesn't (tests run with the user's permissions by design; an agent with a shell can always act on the machine). The owner turns on private vulnerability reporting once the repository is public.
4. **Code of conduct:** the Contributor Covenant 2.1, adopted by reference rather than copied. Reports go through the same private channel.
5. **Issue forms:** a bug report (what happened, `seamspec --version`, editor, runner, `seamspec doctor`, OS and Python) and an idea form. Links point security reports to the private form and questions to the getting-started guide.

**For the owner to decide before switching:** see the PR. It lists the documents that mention costs, billing and plans, and one claim about another project to re-check.

## Enforced Invariants

None.

## Consequences

- Anyone can read the history, PRs and documents once the owner switches the repository to public.
- The README's relative links still break on PyPI; release step 5 makes them absolute, including the new ones.
