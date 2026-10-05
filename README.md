# SeamSpec

**Build first; every seam that works gets a spec.**

SeamSpec is an open-source governance layer for AI coding agents. When something works, it proposes a plain-language rule plus a test that proves it; once a human approves, hooks, pre-commit and CI stop the agent from silently breaking it.

> **Status:** pre-release, under active development. v0.1 targets Claude Code with pytest and vitest. Nothing here is usable yet.

## Docs

- [Design spec](docs/SPEC.md): the full design, kept current as the code evolves.
- [Decisions](docs/adr/README.md): ADRs for anything that changes or adds to the spec.
- [Progress](docs/PROGRESS.md): what's done, in progress and next (plus GitHub milestones, one per roadmap week).

## License

[Apache-2.0](LICENSE)