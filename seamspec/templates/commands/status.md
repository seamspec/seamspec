---
name: status
description: Show where SeamSpec stands in this repository. Mode, rules by status, dead ends, pending reviews and the last check. Use when the user asks "what's the SeamSpec status?" or "anything waiting for me?".
---
Run `seamspec status --json` with your shell tool and summarize it in plain language: the mode,
how many rules are LOCKED, PROPOSED, SUPERSEDED and REJECTED, active dead ends, what is waiting
for the user's review, and the result of the last verify. If something is waiting, say exactly
what the user should run next (usually `seamspec review`).
