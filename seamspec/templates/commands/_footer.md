---
Rules for every SeamSpec command:
- Never approve invariants and never edit files under `.seamspec/` directly.
- `propose_invariant` never runs tests. After proposing, run `seamspec verify --proposed <ids>`
  with your shell tool; the user may be asked to allow it. Never try to work around that prompt.
- If SeamSpec MCP tools are unavailable, use the CLI instead: `seamspec context <files>`,
  `seamspec propose --json -`, `seamspec dead-end --json -`, `seamspec verify --json`.
- End your reply with the SeamSpec summary block:

  SeamSpec · <command>
  ✅ <created or passed items, with ids>
  ⏭  <dismissed or skipped items>
  ⚠️ <failures or items needing attention>
  Next: <one action for the user, e.g. "run `seamspec review` (3 pending)">
