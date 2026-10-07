"""Locked rule: the MCP server never runs proposed (unapproved) tests; its verify tool only runs
LOCKED rules (SPEC §12.4.3 rule 1)."""

import anyio
from mcp import Client

from seamspec.mcp_server import mcp


def test_verify_tool_refuses_proposed_scope() -> None:
    async def go():
        async with Client(mcp) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            scopes = tools["verify"].input_schema["properties"]["scope"]["enum"]
            result = await client.call_tool("verify", {"scope": "proposed"})
            return scopes, result

    scopes, result = anyio.run(go)
    assert sorted(scopes) == ["all", "changed"]
    assert result.is_error
