# BRAINDUMP.md

<!--
Your scratchpad. Write anything here: half-formed rules, decisions, things that didn't work,
pasted snippets. Bullets or paragraphs, in any order. For example:

  - Tenant isolation must never leak if org_id is missing from the header.
  - Error format should be RFC 7807 problem details everywhere.
  - Tried caching JWT validation in a global dict: it leaked across tenants. Don't.

When you want, ask the agent to sort it (/seamspec:drain, or just "sort my braindump"). Rules it
proposes still wait for your approval in `seamspec review`. SeamSpec only reads above the marker
below and never changes what you wrote, unless you run `seamspec drain --tidy`.
This file is git-ignored, so it stays yours; remove it from .gitignore to share it with your team.
-->

<!-- seamspec:processed -->
## Processed (managed by SeamSpec)
