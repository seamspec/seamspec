---
id: ADR-20261105-5c1d
title: init asks before setting up a folder that isn't a git repository
status: ACCEPTED
date: 2026-11-05
scopes: ["seamspec/cli.py"]
invariants: []
supersedes: null
superseded_by: null
---

# init asks before setting up a folder that isn't a git repository

## Context

While updating SessionWalk, the owner ran `seamspec init --hosts antigravity` from `~/Documents/seamspec`, the folder that holds the SeamSpec repository and other projects, instead of from SessionWalk. `init` set that folder up as a new project: `.seamspec/`, `CLAUDE.md`, `AGENTS.md`, a CI workflow, Antigravity's files, and the Claude Code plugin enabled there. Only after writing all of it did it note "not a git repository". The owner answered yes to every question, because the questions were about consent, CI and the plugin, never about the folder. Cleaning up took a move to the Trash and a plugin uninstall.

SeamSpec needs git for most of what it does: the journal and frozen-field checks compare with `HEAD`, the commit check is a git hook, and CI runs on pushes.

## Decision

Before writing anything, a **new** setup (no `.seamspec/config.toml` yet) in a folder that **isn't inside a git work tree** says so, and:

- names the git repositories directly inside it, if any, asking whether the person meant one of them;
- in a terminal, asks *"Set SeamSpec up here anyway? [y/N]"*. No (the default) writes nothing and says to run `init` in the project's folder or `git init` first;
- without a terminal, refuses when the folder holds git repositories (almost certainly the wrong folder), and sets up a plain folder as before, so scripted setups and projects not yet in git keep working.

A subfolder of a repository (a monorepo package) counts as inside git and isn't asked. A folder already set up isn't asked again.

Alternatives: refusing every non-git folder, rejected because a project may be set up before its first `git init`; a `--allow-no-git` flag, not needed while a terminal can answer yes.

## Enforced Invariants

None new.

## Consequences

- The mistake above now stops at one question with "No" as the default.
- Tests that simulate a person at a terminal run `init` in a git repository, as a real project would be.
