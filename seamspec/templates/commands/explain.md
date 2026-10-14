---
name: explain
description: Have SeamSpec's reviewer, a separate read-only agent that didn't write the code, explain in plain language what is waiting for review (proposed rules, supersede requests, dead ends) before the user decides. Use when the user asks what is pending, what a rule means, or whether to approve it.
argument-hint: "[ids]"
---
Get an independent explanation of what is waiting for SeamSpec review. Ids, if any: {{args}}

1. Launch the `seamspec:reviewer` agent. Give it exactly this task and nothing more:
   "Explain the items waiting for SeamSpec review." followed by the ids above, if any.
   Don't add your own account of the work, what you meant to build, or what you think of the
   tests: the point is a reader who didn't write them.
2. Show the user the reviewer's answer in full and unchanged, under the line
   "From SeamSpec's reviewer (a separate agent that read the rules and tests; it didn't write them):".
   Don't shorten, reorder or soften it. If you disagree with part of it, say so after it, marked
   as your own view.
3. If you can't launch the reviewer, tell the user so. Don't write the explanation yourself as if
   it came from the reviewer.
4. Offer to open `seamspec review` for the user in a terminal they type into (never in your own
   shell, never answer its prompts). The decision is the user's, made there.
