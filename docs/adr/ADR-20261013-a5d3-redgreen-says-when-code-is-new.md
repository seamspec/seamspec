---
id: ADR-20261013-a5d3
title: Red-green says when a "yes" only means the code is new
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-13
scopes: ["seamspec/core/redgreen.py", "seamspec/review.py", "seamspec/chat_review.py"]
invariants: ["inv_77395da3"]
supersedes: null
superseded_by: null
---

# ADR-20261013-a5d3: Red-green says when a "yes" only means the code is new

## Context

Dogfooding finding #9 (2026-10-12). The owner reviewed two rules whose tests covered three brand-new, uncommitted modules. Red-green answered *"Fails without your change: YES (it fails on HEAD and passes with your change)"* for both.

That was true, and it proved almost nothing. On the last commit those modules didn't exist, so the tests failed at their first `import`. **Any** test of new code fails that way, including one whose asserts check nothing. The reviewer reads "YES" as "this test would catch a wrong change", which is the one thing the check had not shown. For a test of new code this is the normal case, not an edge case: most proposals arrive right after the code is written.

The verdict didn't distinguish the two kinds of failure, and didn't show what failed on HEAD, so the reviewer couldn't tell either.

## Decision

1. **A "yes" is split in two by what failed on HEAD**, read from the runner's report (`RunnerResult.checks`, ADR-20261013-4e9b), never from terminal output:
   - **The code is there and behaves differently:** a plain *"YES"*, which now also quotes the failure: *"…; on HEAD: assert 30.0 == 60"*. The reviewer can see it is the behavior the rule is about.
   - **Every failure is the test being unable to import or find what it tests:** *"YES, BUT ONLY BECAUSE THE CODE IS NEW (the last commit doesn't have what this test needs: ModuleNotFoundError: …. Expected for new code, but it doesn't show the test would catch a wrong change)"*.
2. **The second kind comes with something to do:** *"To see this test catch something: break the new code on purpose, run `seamspec verify --proposed <id>`, and check that it fails."* That is the check the owner was advised to ask the agent for; now the review says it.
3. **What counts as "can't find what it tests":** `ModuleNotFoundError`, `ImportError`, `FileNotFoundError`, `NameError`, an `AttributeError` on a module or a class, and in JavaScript *"is not a function"*, *"is not defined"*, *"is not a constructor"*, *"Cannot find module"*, *"Failed to resolve import"*, *"does not provide an export named"*. All failures of the test on HEAD must match; one real assertion failure makes it a plain "yes".
4. **The verdict value stays `yes`**; `RedGreen.new_code` marks the weaker kind. Callers that only look at the verdict are unaffected. Still information, never a gate.
5. **Without a usable report** (`report = "none"`, or the runner wrote none) the answer is the plain "yes" it was before, with nothing quoted.

**What this does not do:**
- **It doesn't prove a plain "yes" is a good test.** It shows the test failed on real behavior of the old code; whether that is the behavior the rule describes is for the reviewer, who now sees the failing line.
- **An `AttributeError` on an instance** (`'NoneType' object has no attribute …`, a new method on an existing class) is treated as a plain "yes": the code ran and gave something else. The quoted message lets the reviewer judge.
- **It can't see a test that fails on HEAD for an unrelated reason** (a changed fixture, say). That too shows in the quoted message.

**Alternatives considered:**
- **Call it "COULDN'T TELL".** The test did fail without the change; saying we couldn't tell would be false, and would hide the difference from a real environment problem.
- **Mutate the code automatically** (run the test against a deliberately broken copy). That is mutation testing: slow, language-specific, and the model-free core would have to decide what "broken" means. The hint tells the human how to do the one mutation that matters.
- **Parse the traceback text** for `ImportError`. The report already has each failure's first line, per test case.

## Enforced Invariants

* `inv_77395da3`: red-green never reports a plain YES for code that is only missing on HEAD (approved by the owner in `seamspec review`, 2026-10-13).

## Consequences

- For most proposals of new code the reviewer now reads "…BUT ONLY BECAUSE THE CODE IS NEW". That is less comforting and more accurate, and it sits next to the "what this test checks" list, which is the better evidence for new code.
- A plain "YES" is rarer and worth more: it shows the failing check on the old code.
- The pattern list is a heuristic and will need new entries for new runners and languages (Go, Rust in v0.2).
