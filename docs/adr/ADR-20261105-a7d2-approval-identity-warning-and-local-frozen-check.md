---
id: ADR-20261105-a7d2
title: Warn before a personal email is approved into a rule, and check a locked rule's details locally
status: ACCEPTED
date: 2026-11-05
scopes: ["seamspec/core/lifecycle.py", "seamspec/core/journal.py", "seamspec/review.py", "seamspec/chat_review.py", "seamspec/cli.py"]
invariants: []
supersedes: null
superseded_by: null
---

# Warn before a personal email is approved into a rule, and check a locked rule's details locally

## Context

Two problems came up while dogfooding on the owner's project, SessionWalk:

- **A personal email in ten locked rules.** `approved_by` records the identity git uses for commits (§11.1, ADR-20261006-0f6e). The owner's git config used a Gmail address, so ten approvals committed it. §11.1 says to use a forge noreply address, but nothing said so when it mattered. A locked rule's `approved_by` can't be edited, as `doctor --ci` rightly enforces, so removing the email took a history rewrite of every branch before the repository went public.
- **Local checks saw only the status.** At Stop, pre-commit and in local `doctor`, the journal check compared each rule's status with `HEAD`. A hand edit to a locked rule's title, scope or `approved_by` passed every local check and failed only in CI (`doctor --ci`, which compares the frozen fields with the base branch). Edits to the test or the assertion were already caught locally by the integrity hashes.

## Decision

- **A warning before a personal email is committed.** When the approver's email is at a well-known personal mail provider (Gmail, Outlook, Yahoo, iCloud, Proton and similar), SeamSpec says so: as a note in `seamspec init`; at the start of `seamspec review` when there is anything to approve, asking *"Continue with this address?"* (default yes; no stops before anything is decided); and as a note in the chat review dialog. It names the address and the fix (`git config user.email` with a noreply address).
- **Only personal providers are flagged.** A work address in a work repository is expected, and warning about every address that isn't noreply would train people to ignore it. A personal address on its own domain isn't caught; the SPEC note stays the guidance for that.
- **The local journal check compares the frozen fields too.** For every rule `LOCKED` at `HEAD` and still `LOCKED`, the fields `doctor --ci` freezes (`title`, `assertion`, `scope`, `verification`, `approved_at`, `approved_by`) must match `HEAD`. A difference is a journal problem: it blocks the Stop gate and the commit, and is an error in `doctor`, with the `git checkout HEAD -- <record>` that reverts it. The CLI never edits those fields in place (`critical` isn't one of them), so nothing it does is flagged. `FROZEN` moves to `journal.py`, and `doctor` uses the same list.

Alternatives: blocking approval with a personal email, rejected because keeping it is a legitimate choice for a private repository; a `doctor` warning, rejected because it would repeat forever for someone who chose to keep the address.

## Enforced Invariants

None new.

## Consequences

- Someone about to commit a personal email into a rule hears about it before the first approval, when changing it is still one git command.
- A hand edit to a locked rule is caught at the next Stop or commit, not first in CI.
- A history rewrite still passes every check, since it changes `HEAD` and the base as well; that is by design and the reason the warning comes first.
