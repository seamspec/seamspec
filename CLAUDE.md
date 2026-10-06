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

<!-- From week 3, `seamspec init` adds its own marked directive block below (SPEC §18), when SeamSpec starts governing this repo. -->
