# Working on SeamSpec

SeamSpec is an open-source governance layer for AI coding agents: when something works, it proposes a plain-language rule plus a test; once a human approves, hooks, pre-commit and CI stop the agent from silently breaking it.

## Start here

1. [`docs/PROGRESS.md`](docs/PROGRESS.md): what's done, in progress and next. **Read it first.**
2. [`docs/SPEC.md`](docs/SPEC.md): the full design. §22 is the roadmap; §19 and §21 are the reference code and package layout.
3. The current week's GitHub issue (milestones `v0.1 · Week 1` … `Week 6`, `v0.2`): the checklist for this week.
4. [`docs/adr/`](docs/adr/README.md): why the design changed.

## Rules

- **Spec and code agree.** If code needs to differ from SPEC.md, update the affected section in the same commit.
- **Anything that changes or adds to the spec, or changes this build process, gets an ADR** in `docs/adr/` (format and file naming in `docs/adr/README.md`). Plain implementation detail doesn't.
- **Branches and PRs only, never push to `main`** (ADR-20261005-d8bc). Branch names: `week-N/<topic>`, `docs/<topic>`, `fix/<topic>`, `chore/<topic>`. One PR per deliverable, filled in from `.github/pull_request_template.md`, with `Part of #N` for the week's issue. The owner squash-merges.
- **Request a Copilot review on every PR you open** (`gh pr edit <n> --add-reviewer @copilot`; automatic requests don't work on this private free-plan repo). Before asking the owner to merge, address each finding (fix it and reply, or reply why not) and say so in the PR (ADR-20261005-c076).
- **Log progress in the PR:** update `docs/PROGRESS.md` in the same PR as the code; tick the week's issue checklist once the PR is merged.
- **Clean room:** never read, copy or look at competitors' code. Public descriptions (READMEs, websites, docs) may inform positioning only.
- **Model-free core:** SeamSpec itself never calls an LLM (SPEC §3).
- **Never publish** to PyPI or npm (`uv publish`, `twine upload`, `npm publish`, version bumps meant for release) without the owner's explicit go-ahead for that specific release (ADR-20261005-3adc). To try SeamSpec, install the checkout: `uv tool install --force --editable .`
- `notes/` is git-ignored private material. Nothing in it is needed to continue the build.

## Tech

Python ≥ 3.11, uv (flat layout: the package is `./seamspec`), pytest, ruff. Dependencies per SPEC §19.

```bash
uv sync                                   # install
npm ci --prefix tests/fixtures/ts_repo    # pinned vitest for the vitest tests (else they skip)
uv run pytest                             # tests
uv run ruff check . && uv run ruff format --check .
uv run seamspec --help                    # the CLI
```

- **Implemented modules are the source of truth**; SPEC §19 keeps a short contract per module (ADR-20261005-6f2a). If you change a module's behavior, update its §19 contract.
- `seamspec/schemas/v1/config.json` is generated: after changing `core/config.py`, regenerate it from `config_json_schema()` (a test fails if it's stale).
- Never run `ruff format` on `docs/` (it's excluded): SPEC code blocks are edited by hand.
- **Lint a rule test before you propose it** (`ruff format` and `ruff check` on the file): once a human approves it, it is locked by hash and can't be tidied. `.seamspec/` is excluded from ruff for that reason (ADR-20261013-c3f7).
- After editing `seamspec/templates/directive.md`, run `uv run python -m seamspec.installers.directive`: it adds the new lines to `directive_known_lines.txt`, so `init` keeps telling SeamSpec's own wording from lines a user wrote inside the block (a test fails if the file is behind; ADR-20261011-b1c8).
- Plugin skills are generated: after editing `seamspec/templates/commands/`, run `uv run python -m seamspec.core.commands` (a test fails if `seamspec-plugin/skills/` is stale). Try the plugin with `claude --plugin-dir seamspec-plugin`, or install it for a repo with `seamspec init --plugin` (local scope). Tests get a throwaway `CLAUDE_CONFIG_DIR`; never run `claude plugin install` against the owner's real settings without asking.

<!-- From week 3, `seamspec init` adds its own marked directive block below (SPEC §18), when SeamSpec starts governing this repo. -->

<!-- seamspec:begin (managed by `seamspec init`; edit outside these markers) -->
# SeamSpec Protocol

This repository uses SeamSpec. Locked invariants are enforced by hooks and git pre-commit (and by
CI where the SeamSpec workflow is installed): failing them blocks you from finishing and blocks commits.

1. Before editing a file, call `get_constraints(files)` (or run `seamspec context <files>`).
   Respect every LOCKED invariant. Approaches listed as previously failed (dead ends) failed for
   the stated reason; don't reuse them unless that reason no longer applies.
2. When the user states an agreement or a rule the code must keep, or you establish a behavior
   worth protecting, capture it right away: call `propose_invariant` with a focused,
   behavior-level test (not implementation details). If its code doesn't exist yet, say so and
   propose it once the code works. The tool does not run the test: run
   `seamspec verify --proposed <id>` with your shell tool and fix the test until it passes.
   If the project keeps a list of rules it intends to lock (for example a section of its
   plan), propose each one when its code exists and works.
3. When an approach fails, or the user tells you about one that failed before, call
   `log_dead_end` with what was tried and why it failed.
4. If your change must intentionally break a LOCKED invariant, do not edit or delete its test.
   Call `request_supersede(invariant_id, reason, replacement_id)` and tell the user.
5. Never edit files under `.seamspec/` directly; use SeamSpec tools. If they are missing or fail,
   use the matching `seamspec` command in your shell (`seamspec --help`). Never search outside
   this project for SeamSpec's settings; if neither works, stop and tell the user.
6. BRAINDUMP.md holds the user's own notes. Never edit it. When asked to sort it, follow
   `/seamspec:drain`. When SeamSpec reports new notes at the start of a session, ask the user once
   whether to sort them; don't sort without a yes, and don't ask again this session after a no.
7. Only humans approve invariants. When proposals are pending, offer an explanation from
   SeamSpec's reviewer (`/seamspec:explain`), and offer to open `seamspec review` for the user in a
   terminal they type into (never in your own shell; never answer its prompts), or remind them to
   run it.
8. When the user runs a `/seamspec:*` workflow command, follow its steps exactly and end with
   the SeamSpec summary block.
9. Users don't have to type commands. Treat plain requests as the matching workflow command:
   "sort my braindump" → drain; "protect this" / "lock that" / an agreement the user states → lock;
   "that didn't work" / a failure the user describes → dead-end;
   a changed requirement for a LOCKED rule → supersede; "what applies here?" → context;
   "wrap up" → checkpoint.
<!-- seamspec:end -->
