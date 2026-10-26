# Security

SeamSpec runs your project's tests on your machine: at the end of an agent's task, before each commit and in CI. So a bug in how it decides **what runs, and when**, can matter more than an ordinary bug. Thank you for reporting one privately.

## Report a problem

Please **don't open a public issue.** Use GitHub's private report instead:

1. Go to the [Security tab](https://github.com/seamspec/seamspec/security) of this repository.
2. Choose **Report a vulnerability**.

Only the maintainers see the report. We aim to reply within a week, and we'll tell you how we plan to fix it before anything is published. If you'd like credit, we'll name you in the release notes.

## What counts

These are examples, not a complete list:
- **Running code without consent:** SeamSpec runs tests, or a runner command, in a clone that wasn't trusted or where automatic runs weren't allowed (`seamspec init`, `seamspec trust`).
- **Approving without a person:** an agent, a hook or a crafted file locks, retires or rejects a rule without a person approving it in `seamspec review` (or in a chat review, when that's switched on).
- **Bypassing the guard:** a change that breaks a locked rule passes the commit check or `seamspec verify --ci` without a supersede approved by a person. Or a rule's test is edited, emptied or skipped without the hash check noticing.
- **Leaking secrets:** environment secrets reaching a rule test, or secrets from BRAINDUMP notes or prompts reaching a committed record.
- **The MCP server or hooks** reading or writing outside the project they were started for.

## Not a vulnerability

- **The tests themselves run with your permissions, with no sandbox.** SeamSpec says so before it asks for consent (SPEC §12.4). A rule test you approved can do anything your user can.
- **An agent with shell access can always run commands or edit files.** SeamSpec guards what reaches a commit and CI, not what an agent can do on your machine.
- **Settings you chose,** such as `advisory` mode, which runs nothing automatically.

## Supported versions

Fixes go into the latest release. SeamSpec is pre-1.0, so there are no older lines to patch.
