---
id: ADR-20261005-cc29
title: MCP server on the MCP Python SDK 2.x
status: ACCEPTED            # PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
date: 2026-10-05
scopes: ["seamspec/mcp_server.py", "seamspec/cli.py", "pyproject.toml"]
invariants: []
supersedes: null
superseded_by: null
---

# ADR-20261005-cc29: MCP server on the MCP Python SDK 2.x

## Context
Week 3's second slice is the MCP server (SPEC §14). The reference listing in §19.11 used `from mcp.server.fastmcp import FastMCP`, the 1.x API. The current SDK is 2.x (2.3.0 at the time), where that import fails with a pointer to the migration guide: `FastMCP` was renamed `MCPServer`.

## Decision

1. **Use the MCP Python SDK 2.x** (`mcp>=1.10` in `pyproject.toml` resolves to 2.x; `from mcp.server.mcpserver import MCPServer`). The decorator API (`@mcp.tool()`, `@mcp.resource(uri)`) is the same shape, so the §14 design is unchanged.
2. **The v0.1 surface is exactly 5 tools and 2 resources** (§14). A test fails if the tool list changes or the definitions exceed the 1,500-token budget (≈ 1,000 tokens today).
3. **`verify` over MCP obeys the same rule as the Stop hook:** it runs only LOCKED rules, and only where automatic runs are allowed (consent + trust). Otherwise it returns `not_permitted`. An agent can't use MCP to run tests in an untrusted clone.
4. **Errors are data, not exceptions.** Every tool returns `{"error": ..., "message": ...}` (`not_a_seamspec_project`, `invalid`, `queue_full`, `not_permitted`), so the agent can read and act on them.
5. **`get_constraints` also returns the runner hint** (which runner fits these files, and where its tests go), so a first proposal uses the right runner without guessing (§12A.6–7).
6. **Tested through a real MCP client:** in-process (`mcp.Client(server)`) and over stdio by launching `seamspec mcp`, the way the plugin will.

**Alternatives considered:**
- *Pin `mcp<2` to keep the 1.x API:* rejected; a new project shouldn't start on a superseded major version.

## Enforced Invariants
None yet. Candidate: "MCP `verify` never runs a test in an untrusted clone".

## Consequences
* `mcp` is a runtime dependency, which pulls in its HTTP stack even though SeamSpec only uses stdio.
* SPEC §19.11 is now a contract; the plugin slice adds the MCP prompts and sets `SEAMSPEC_ROOT`.
