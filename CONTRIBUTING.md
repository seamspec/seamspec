# Contributing to SeamSpec

Thanks for taking the time. Bug reports, ideas and pull requests are all welcome.

## Report a bug or ask for something

Open an [issue](https://github.com/seamspec/seamspec/issues/new/choose). For a bug, the template asks for:
- `seamspec --version`;
- your editor;
- the output of `seamspec doctor`.

Those three answer most first questions.

**Security problems:** please don't open an issue. See [SECURITY.md](SECURITY.md).

## Set up

You need Python 3.11+, [uv](https://docs.astral.sh/uv/), git, and Node.js for the vitest tests.

```bash
git clone https://github.com/seamspec/seamspec.git && cd seamspec
uv sync                                   # install
npm ci --prefix tests/fixtures/ts_repo    # pinned vitest for the vitest tests (else they skip)
uv run pytest                             # tests
uv run ruff check . && uv run ruff format --check .
uv run seamspec --help                    # the CLI
```

To try your changes in a real project, install your checkout as the `seamspec` command:

```bash
uv tool install --force --editable .
```

## Make a change

1. **Branch and open a pull request** against `main`. Fill in the PR template.
2. **Tests and lint pass:** `uv run pytest`, `uv run ruff check .` and `uv run ruff format --check .`. Add a test for the behaviour you change. For a bug, add one that fails without your fix.
3. **The spec and the code agree.** [`docs/SPEC.md`](docs/SPEC.md) is the design, and §19 keeps a short contract for each module. If you change what a module does, update its contract in the same PR.
4. **Design changes get a decision record.** A change to behaviour, a format, a command, a config key or a default gets an ADR in [`docs/adr/`](docs/adr/README.md); the README there explains the format. Small fixes that match the spec don't need one.

A few things that are easy to miss:
- **Generated files.** After editing `seamspec/templates/commands/`, run `uv run python -m seamspec.core.commands`. After editing `seamspec/templates/directive.md`, run `uv run python -m seamspec.installers.directive`. After changing `seamspec/core/config.py`, regenerate `seamspec/schemas/v1/config.json`. A test fails when any of them is stale.
- **Don't run `ruff format` on `docs/`.** It's excluded on purpose: the spec's code blocks are edited by hand.
- **SeamSpec itself never calls an AI model** (SPEC §3). Keep it that way.
- **Write your own code.** Don't copy code from other spec or agent tools. Their public docs are fine for ideas.

## SeamSpec guards this repository too

This repo uses SeamSpec on itself: the rules in `.seamspec/` run in CI (the `seamspec` check) on every pull request. If your change breaks one on purpose, say why in the PR. A maintainer then retires or replaces the rule. Rules are never edited directly.

To have the same checks run on your machine before each commit:

```bash
seamspec init
```

## Licence

SeamSpec is licensed under [Apache-2.0](LICENSE). By contributing, you agree that your contribution is licensed under the same terms (section 5 of the licence). There is no separate agreement to sign.

## Conduct

Be kind and assume good intent. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
