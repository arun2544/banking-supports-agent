"""MCP hub for banking agents with read-only tool restrictions."""

import copy
import os
import sys
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SERVERS = {
    "accounts": os.path.join(ROOT, "mcp_servers", "accounts_server.py"),
    "transactions": os.path.join(ROOT, "mcp_servers", "transactions_server.py"),
    "service": os.path.join(ROOT, "mcp_servers", "service_server.py"),
}

# Only explicitly permitted read-only tools are enabled.
READ_ONLY_TOOLS = {
    "accounts": {
        "list_accounts",
        "get_balance",
        "get_credit_card_info",
    },
    "transactions": {
        "get_recent_transactions",
        "search_transactions",
        "get_flagged_transactions",
    },
    # Completely disable the service server's tools.
    "service": set(),
}


class MCPHub:
    def __init__(self):
        self.stack = AsyncExitStack()
        self.sessions: dict[str, ClientSession] = {}
        self.tools: dict[str, list] = {}

    async def start(self):
        env = {**os.environ, "PYTHONPATH": ROOT}

        for name, script in SERVERS.items():
            params = StdioServerParameters(
                command=sys.executable,
                args=[script],
                env=env,
            )

            read, write = await self.stack.enter_async_context(
                stdio_client(params)
            )

            session = await self.stack.enter_async_context(
                ClientSession(read, write)
            )

            await session.initialize()
            self.sessions[name] = session

            # Discover tools, then filter using the read-only allowlist.
            discovered = (await session.list_tools()).tools
            allowed = READ_ONLY_TOOLS.get(name, set())

            self.tools[name] = [
                tool for tool in discovered
                if tool.name in allowed
            ]

            print(
                f"[MCP] {name}: enabled tools = "
                f"{[tool.name for tool in self.tools[name]]}"
            )

    async def stop(self):
        await self.stack.aclose()

    def anthropic_tools(self, server: str) -> list[dict]:
        """Expose only allowlisted read-only tools to the agent."""

        if server not in READ_ONLY_TOOLS:
            return []

        output = []

        for tool in self.tools.get(server, []):
            if tool.name not in READ_ONLY_TOOLS[server]:
                continue

            schema = copy.deepcopy(tool.inputSchema)

            # user_id must come from the authenticated user.
            schema.get("properties", {}).pop("user_id", None)

            schema["required"] = [
                item for item in schema.get("required", [])
                if item != "user_id"
            ]

            output.append({
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": schema,
            })

        return output

    async def call(
        self,
        server: str,
        tool: str,
        args: dict,
        user_id: str,
    ) -> str:
        """Execute only explicitly allowlisted read-only tools."""

        if server not in READ_ONLY_TOOLS:
            return "ERROR: Server access is not allowed."

        if tool not in READ_ONLY_TOOLS[server]:
            return (
                "ERROR: This operation is disabled. "
                "The chatbot is read-only."
            )

        available = {
            item.name for item in self.tools.get(server, [])
        }

        if tool not in available:
            return "ERROR: Tool is unavailable."

        # Prevent the model from overriding authenticated user identity.
        safe_args = {
            key: value
            for key, value in args.items()
            if key != "user_id"
        }

        safe_args["user_id"] = user_id

        result = await self.sessions[server].call_tool(
            tool,
            safe_args,
        )

        text = "".join(
            getattr(content, "text", "")
            for content in result.content
        )

        if result.isError:
            return f"ERROR: {text}"

        return text