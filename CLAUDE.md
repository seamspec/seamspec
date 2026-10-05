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
- **Log progress before you stop:** update `docs/PROGRESS.md` and tick the week's issue checklist in the same commit as the code.
- **Clean room:** never read, copy or look at competitors' code. Public descriptions (READMEs, websites, docs) may inform positioning only.
- **Model-free core:** SeamSpec itself never calls an LLM (SPEC §3).
- `notes/` is git-ignored private material. Nothing in it is needed to continue the build.

## Tech

Python ≥ 3.11, uv, pytest, ruff. Dependencies per SPEC §19: `mcp`, `pydantic>=2`, `typer`, `rich`, `pathspec`, `filelock`, `jsonschema`.

<!-- From week 3, `seamspec init` adds its own marked directive block below (SPEC §18), when SeamSpec starts governing this repo. -->
