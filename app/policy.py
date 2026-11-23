"""Role-based permissions. Enforced INSIDE the MCP servers, never by the LLM."""
TOOL_POLICY = {
    # tool name -> tiers allowed (absent = every authenticated customer)
    "increase_credit_limit": {"premium"},
}
MAX_LIMIT_BY_TIER = {"premium": 500_000}


def authorize(tier: str, tool: str) -> bool:
    allowed = TOOL_POLICY.get(tool)
    return allowed is None or tier in allowed
