"""Authorisation (separate from authentication): which agents/tools a customer tier may reach.
Checked by the Coordinator before delegating AND again inside the MCP servers (defence in depth)."""
from . import policy
from .observability import log, metrics

AGENT_ACCESS = {
    "accounts": {"premium", "standard"},
    "transactions": {"premium", "standard"},
    "service": {"premium", "standard"},
}


def check_agent(user: dict, agent: str) -> bool:
    ok = user["tier"] in AGENT_ACCESS.get(agent, set())
    metrics.inc("authz_decisions_total", agent=agent, allowed=str(ok).lower())
    log("authz", user=user["id"], tier=user["tier"], agent=agent, allowed=ok)
    return ok


def check_tool(tier: str, tool: str) -> bool:
    return policy.authorize(tier, tool)
