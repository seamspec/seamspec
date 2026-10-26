---
id: ADR-20261017-7b0e
title: "Rerunning init keeps an earlier yes to automatic test runs"
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-17
scopes: ["seamspec/cli.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261017-7b0e: Rerunning init keeps an earlier yes to automatic test runs

## Context

During the VS Code hands-on test, the owner reran `seamspec init --hosts vscode` in a project where automatic test runs were already allowed. `init` showed the consent screen again and asked *"Allow automatic test runs in this repository? [y/N]"*. The default is No, so one Enter, while only meaning to add an editor, would have recorded "no", and the Stop and pre-commit checks would have stopped running. Rerunning `init` is the normal way to add an editor or pick up a new SeamSpec version, so this would happen to real users.

## Decision

In a terminal, when this machine already consented in this repository and the clone is trusted, `init` doesn't ask. It prints *"Automatic test runs: already allowed on this machine (`seamspec init --mode advisory` stops them)."* It still asks:
- on a first setup;
- on a fresh clone whose committed runner commands this machine hasn't trusted (the one question covering consent and trust, ADR-20261005-9b8f);
- when the earlier answer was no.

Lowering the mode remains the way to stop automatic runs, and it still needs a human.

**Alternatives considered:**
- **Ask again with Yes as the default:** a consent question that defaults to yes is no longer consent.
- **A `--keep-consent` flag:** the safe behaviour should be the default, not an option people must know about.

## Enforced Invariants

None yet.

## Consequences

- A rerun can no longer switch the checks off by accident.
- Withdrawing consent stays explicit (`seamspec init --mode advisory`).
