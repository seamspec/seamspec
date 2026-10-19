---
id: ADR-20261019-e2f8
title: "`seamspec verify` in a clone never set up on this machine says to run `seamspec init`"
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-19
scopes: ["seamspec/cli.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261019-e2f8: `seamspec verify` in a clone never set up here says to run `init`

## Context

In the second-actor benchmark (ADR-20261019-c71d), a teammate's agent worked in a fresh clone whose owner had never run `seamspec init`. It ran `seamspec verify`, got *"This clone is not trusted (this clone has never been trusted). Run `seamspec trust`."*, reported *"I couldn't run `seamspec verify`, so the three locked invariants were not checked"*, and carried on. CI caught the change on push, but the person at the keyboard was never told how to get the checks running locally. And `seamspec trust` alone isn't the right step for a clone this machine never set up: `init` also asks for automatic-run consent and installs the hooks.

## Decision

When `verify` refuses to run because the clone isn't trusted, and this machine has neither consent nor trust recorded for it (a clone never set up here), the message says:
- SeamSpec isn't set up for this clone on this machine, so its locked rules can't run here yet;
- run `seamspec init` in a terminal: it shows the test commands the repository would run and asks first;
- *"Agents: tell the user this, and that CI still checks the rules on every push."*

A clone that was set up but whose runner commands or locked tests changed keeps the existing *"not trusted … Run `seamspec trust`"*. Nothing runs without trust either way.

**Alternatives considered:**
- **Let `verify` run in an untrusted clone:** the trust check exists so that a clone's committed commands never run on someone's machine unseen (§12.4.6).
- **Change the protocol instead:** the message reaches every agent that runs `verify`, including ones on hosts without SeamSpec's protocol block.

## Enforced Invariants

None yet.

## Consequences

- A teammate's agent now tells them how to get SeamSpec's checks running, instead of quietly skipping them.
