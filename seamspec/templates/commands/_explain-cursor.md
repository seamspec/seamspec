Get an independent explanation of what is waiting for SeamSpec review. Ids, if any: {{args}}

1. Use the `seamspec-reviewer` subagent (read-only). Give it exactly this task and nothing more:
   "Explain the items waiting for SeamSpec review." followed by the ids above, if any. Don't add your
   own account of the work, what you meant to build, or what you think of the tests: the point is a
   reader who didn't write them.
2. Show the user the reviewer's answer in full and unchanged, under the line
   "From SeamSpec's reviewer (a separate agent that read the rules and tests; it didn't write them):".
   Don't shorten, reorder or soften it. If you disagree with part of it, say so after it, marked
   as your own view.
3. If you can't start the subagent, tell the user so, and that they can type `/seamspec-reviewer`
   themselves. Don't write the explanation yourself as if it came from the reviewer.
4. Offer to open `seamspec review` for the user in a terminal they type into (never in your own
   shell, never answer its prompts). The decision is the user's, made there.
