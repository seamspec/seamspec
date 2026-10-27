---
id: ADR-20261027-c3a0
title: Docs fixes from the catch-up review; init keeps the CODEOWNERS reviewers a person wrote
status: ACCEPTED
date: 2026-10-27
scopes: ["seamspec/installers/ci.py", "seamspec/cli.py", "docs/getting-started.md", "docs/benchmark/full-1-haiku.md", "bench/README.md", "docs/PROGRESS.md", "docs/SPEC.md"]
invariants: []
supersedes: null
superseded_by: null
---

# Docs fixes from the catch-up review; init keeps the CODEOWNERS reviewers a person wrote

## Context

The catch-up review of #53 to #95 (drafts #98, #99 and #100, 2026-10-26) found six problems in documents and one test:

1. **`full-1-haiku.md` still gave $3.11** as the batch's cost. `full-1.md` already corrected it to $1.24 (the running-total overcount, ADR-20261018-6e1a), but this page had no correction, and its per-run costs and medians were overstated the same way.
2. **`bench/README`'s full-run command scheduled 150 runs,** not 120: `--conditions` defaults to every setup, and N and S were added after the command was written.
3. **The getting-started guide promised that CODEOWNERS makes the right people review** rule changes, but `init` writes a placeholder owner and nothing makes GitHub require the review.
4. **The "remove completely" steps left the commit hook behind.** It then refuses the commit that removes SeamSpec, because the config is still in the last commit. The steps also missed hook managers, editor files, CODEOWNERS and a required CI check.
5. **PROGRESS still listed done work as next,** the paid benchmarks included.
6. **The critical-rule test compared two passing runs,** so it would also pass if critical rules were skipped.

Fixing item 3 showed a code gap: `install_codeowners()` rebuilt its block with the placeholder on every run. Replacing `@your-team/leads`, as the guide now says, was undone by the next `init` in strict mode (to add an editor, say). Its first line also contains the placeholder, so a find-and-replace over the file changed the marker too, and the next run appended a second block.

## Decision

1. **The Haiku page's costs are recomputed from the saved logs** (each session's final running total, summed per run). The total is $1.24, matching `full-1.md`, with a note giving the first figure. No other number changes. ADR-20261013-e2b6 keeps its figures as a dated record, as it does for the main run's.
2. **The full-run command names A–H,** and the README says why.
3. **The guide gives both CODEOWNERS steps:** name real reviewers with write access, and turn on **Require review from Code Owners**. The claim says it holds once both are done.
4. **The removal steps come in order:** advisory mode first (it removes the hook), the plugin, the required check, then the files, the commit and the command.
5. **PROGRESS marks the done items done** and points to the release steps. The stale "In progress" line goes too.
6. **The test breaks the code first,** and checks that the rule fails the same way with the mark on and off.
7. **`install_codeowners()` keeps the reviewers written in its block.** A folder new to the block gets the reviewers of its first line. Any line starting `# seamspec:begin` opens the block, and a rerun restores its wording. `init` shows the "replace @your-team/leads" hint only while the placeholder is there.

**Alternative considered:** *keep reviewers outside the block* (CODEOWNERS uses the last matching line). That works only when the person's lines come after the block, which is easy to get wrong.

## Enforced Invariants

None new. `tests/test_ci_installer.py::test_rerunning_init_keeps_the_reviewers_someone_wrote` covers point 7; `tests/test_critical.py` now fails if a critical rule isn't run.

## Consequences

- A strict-mode project that already named reviewers keeps them when `init` reruns.
- Benchmark cost estimates made from the Haiku page drop to about a third.
