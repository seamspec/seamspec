---
id: ADR-20261013-7c2e
title: A rule is retired only after its replacement is locked; the review decides both as one
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-13
scopes: ["seamspec/core/lifecycle.py", "seamspec/review.py", "seamspec/chat_review.py"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261013-7c2e: A rule is retired only after its replacement is locked; the review decides both as one

## Context

Dogfooding finding #10 (2026-10-12). In the owner's project the agent was asked to change a locked behavior ("retry 5 times instead of 4"). It proposed a replacement rule and filed a supersede request, as the protocol asks. In `seamspec review`:

1. The supersede request came first. The owner approved it, and the old rule was retired **at once**.
2. Next came an unrelated proposal that had been waiting.
3. Only then came the replacement, on a card that didn't say it replaced anything.

Between steps 1 and 3 nothing protected the attempt count. If the owner had quit the review there, or skipped the last card out of habit (it looked like any other proposal), the old rule would have been gone with nothing in its place. The design said so openly ("the replacement still needs its own approval"), but the order made the safe outcome depend on the reviewer finishing the list.

## Decision

1. **`lifecycle.supersede` refuses while the replacement is only proposed.** The error says to approve the replacement first. This is the one place every path goes through (`seamspec review`, `seamspec supersede`, the chat dialogs), so no interface can leave the gap. A missing or rejected replacement is refused as before. A retirement with no replacement stays possible.
2. **In `seamspec review`, a request and its proposed replacement are one item and one decision.** The reviewer sees two blocks, *"the rule that would stop running"* and *"its replacement"*, the optional red-green check for the replacement, and one prompt: *approve the replacement and retire the old rule*, *decline*, *skip* or *quit*. Approving locks the replacement first (running its test, as any approval does) and retires the old rule only if that worked.
3. **The replacement is never offered on its own** while its request is pending: it is left out of the proposals list and counted with its request (*"1 supersede request(s) (1 with a replacement rule)"*).
4. **Declining keeps the old rule and asks *"Also reject the replacement?"*** (default yes), since the two usually contradict each other. Answering no leaves it as an ordinary proposal.
5. **A card says what the rule replaces:** *"Replaces: inv_… · title (still locked; retired when its supersede request is approved)"*, and *"(retired)"* once it has happened.
6. **A request with no replacement** is shown with *"No replacement: after this, no rule protects this behavior."* A request whose replacement was rejected or is missing can't be approved from the review; it says why and offers decline or skip.
7. **In chat** (`open_review`, off by default): the replacement's dialog comes right before its request's dialog. While the replacement isn't locked, the request's dialog offers no *supersede* choice and explains. Asking for a request by id also brings its replacement.

**If something stops between the two steps** (a crash after the replacement is locked), both rules are locked and the old one fails verification. That is loud and blocks commits, which is the safe side; running the review again finishes the swap.

**Alternatives considered:**
- **Keep two separate decisions but show the replacement right after its request.** Still retires the old rule first, so quitting in between still leaves the gap.
- **Show the replacement first, then the request, as two prompts in the terminal too.** Safe, but it asks two questions for what the human thinks of as one change, and approving the first while skipping the second leaves two contradicting locked rules.
- **Make `supersede` lock the replacement itself.** An approval must come from a human who was shown the test (§12.4.3 rule 4). The lifecycle function can't know that; the interface that showed it can.
- **One atomic write for both changes.** The records are separate files and an approval runs a test in between. Ordering the two steps so that the failure mode is "both locked" gets the same safety without a transaction layer.

## Enforced Invariants

To be proposed: "a locked rule is never retired while the replacement named for it is only proposed".

## Consequences

- A supersede can no longer leave a behavior unprotected by being interrupted.
- `seamspec supersede <id> --replacement <new>` now needs `<new>` to be locked first (`seamspec approve <new>`), or the swap is done in `seamspec review`.
- Declining a swap can leave a rejected replacement in the ledger; that is the record of what was asked and refused.
- The chat flow needs the replacement approved before the request can be; a human who skips the replacement sees the request with no *supersede* choice.
