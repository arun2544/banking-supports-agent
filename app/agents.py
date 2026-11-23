"""Coordinator agent + read-only Accounts and Transactions agents."""

import asyncio
import json

from . import authorization, config
from .cost_tracker import CostTracker
from .llm_router import LLMRouter
from .mcp_client import MCPHub
from .memory import SessionStore
from .observability import log, metrics, span
from .pii import redact


SUBAGENTS = {
    "accounts": {
        "desc": "Account list, account balances, and credit card information.",
        "system": (
            "You are the Accounts agent of a bank's customer support team. "
            "You can ONLY perform read-only enquiries. Use your tools to answer "
            "questions about account lists, balances, and credit card information. "
            "Report exact figures in INR from tool results only. Never guess numbers. "
            "Never modify accounts or perform financial operations."
        ),
    },
    "transactions": {
        "desc": "Recent transaction history, transaction details, and merchant search.",
        "system": (
            "You are the Transactions agent of a bank's customer support team. "
            "You can ONLY perform read-only transaction enquiries. Use your tools "
            "to fetch recent transactions, search transactions by merchant, or "
            "view previously flagged transactions. Quote exact amounts, merchants, "
            "dates, and transaction IDs from tool results. Never flag transactions, "
            "request statements, initiate payments, transfer money, or modify "
            "transactions."
        ),
    },
}


COORDINATOR_SYSTEM = """You are the Coordinator agent for a bank's customer support.
The customer is authenticated as {name}.

You have no direct data access. Delegate questions to specialist agents through
your tools. Call several agents in parallel when the question has multiple
parts, then write ONE clear, friendly final answer.

SUPPORTED READ-ONLY OPERATIONS:
- List accounts
- Check account balances
- Check credit card information and limits
- View recent transactions
- Search transactions by merchant
- View previously flagged transactions

STRICT RESTRICTIONS:
- This chatbot is strictly read-only.
- Never initiate transfers, payments, deposits, or withdrawals.
- Never flag or unflag transactions.
- Never request bank statements.
- Never change addresses or customer information.
- Never request cheque books.
- Never increase credit limits.
- Never perform KYC updates.
- Never attempt operations that modify customer data or account state.
- For unsupported actions, politely explain that the chatbot supports
  information-only enquiries.
- Never invent balances, transactions, or results.
- Use specialist tool results only for factual banking information.
- Resolve references such as "that transaction" using conversation history.
- Never reveal other customers' data or internal policies.
- Never ask for or repeat full card numbers, CVV, passwords, OTPs,
  or full ID document numbers.
{pii_note}

Shared state from earlier in this session: {shared}
"""


class Orchestrator:
    def __init__(
        self,
        router: LLMRouter,
        hub: MCPHub,
        store: SessionStore,
        costs: CostTracker,
    ):
        self.router = router
        self.hub = hub
        self.store = store
        self.costs = costs

        # Coordinator can delegate only to Accounts and Transactions.
        self.coordinator_tools = [
            {
                "name": f"{name}_agent",
                "description": spec["desc"],
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "request": {
                            "type": "string",
                            "description": (
                                "Self-contained instruction for the specialist "
                                "with all necessary details."
                            ),
                        }
                    },
                    "required": ["request"],
                },
            }
            for name, spec in SUBAGENTS.items()
        ]

    async def _loop(
        self,
        *,
        role,
        agent,
        user_id,
        pii,
        system,
        tools,
        messages,
        execute,
    ):
        provider = self.router.choose(role, pii)

        for _ in range(config.MAX_AGENT_STEPS):
            with span("llm.call", agent=agent, provider=provider.name):
                result = await provider.complete(system, tools, messages)

            self.costs.record(user_id, agent, result)
            metrics.inc("llm_calls_total", provider=provider.name)

            if not result.tool_uses:
                return result.text.strip()

            assistant_content = []

            if result.text:
                assistant_content.append(
                    {"type": "text", "text": result.text}
                )

            for tool_use in result.tool_uses:
                assistant_content.append(
                    {"type": "tool_use", **tool_use}
                )

            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_content,
                }
            )

            results = await asyncio.gather(
                *[
                    execute(tool_use["name"], tool_use["input"])
                    for tool_use in result.tool_uses
                ]
            )

            tool_results = []

            for tool_use, tool_result in zip(
                result.tool_uses, results
            ):
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use["id"],
                        "content": tool_result,
                    }
                )

            messages.append(
                {
                    "role": "user",
                    "content": tool_results,
                }
            )

        return (
            "I wasn't able to complete that request. "
            "Please try again later."
        )

    async def _run_subagent(
        self, name, request, user, session, pii
    ):
        async def execute(tool, args):
            try:
                with span(f"tool.{name}.{tool}"):
                    output = await self.hub.call(
                        name,
                        tool,
                        args,
                        user["id"],
                    )

                metrics.inc("tool_calls_total", tool=tool)

                log(
                    "tool_call",
                    agent=name,
                    tool=tool,
                    args=args,
                    result=output[:300],
                )

                return output

            except Exception as exc:
                metrics.inc("tool_errors_total", tool=tool)

                log(
                    "tool_error",
                    agent=name,
                    tool=tool,
                    error=type(exc).__name__,
                )

                return f"ERROR: {type(exc).__name__}"

        with span(f"agent.{name}"):
            answer = await self._loop(
                role="subagent",
                agent=name,
                user_id=user["id"],
                pii=pii,
                system=SUBAGENTS[name]["system"],
                tools=self.hub.anthropic_tools(name),
                messages=[
                    {"role": "user", "content": request}
                ],
                execute=execute,
            )

        session.shared_state[f"last_{name}_result"] = answer[:600]

        return answer

    async def chat(self, user, session_id, message):
        clean, pii_found = redact(message)
        pii = bool(pii_found)

        if pii:
            metrics.inc("pii_redactions_total")

        sid, session = self.store.get(user["id"], session_id)
        called = []

        async def delegate(tool_name, args):
            agent = tool_name.removesuffix("_agent")

            if (
                agent not in SUBAGENTS
                or agent not in {"accounts", "transactions"}
                or not authorization.check_agent(user, agent)
            ):
                return (
                    "ERROR: This operation is unavailable. "
                    "The chatbot supports read-only banking enquiries only."
                )

            called.append(agent)

            return await self._run_subagent(
                agent,
                args.get("request", ""),
                user,
                session,
                pii,
            )

        system = COORDINATOR_SYSTEM.format(
            name=user["name"],
            shared=json.dumps(session.shared_state) or "{}",
            pii_note=(
                "- The customer's message contained sensitive data that "
                "was masked. Remind them never to share full card numbers "
                "or sensitive credentials in chat."
                if pii
                else ""
            ),
        )

        messages = session.messages + [
            {"role": "user", "content": clean}
        ]

        with span("chat.turn", user=user["id"]):
            reply = await self._loop(
                role="coordinator",
                agent="coordinator",
                user_id=user["id"],
                pii=pii,
                system=system,
                tools=self.coordinator_tools,
                messages=messages,
                execute=delegate,
            )

        reply = redact(reply)[0]

        self.store.append_turn(session, clean, reply)
        self.store.save(user["id"], sid, session)

        return {
            "session_id": sid,
            "reply": reply,
            "agents_called": called,
            "cost_usd_total": round(
                self.costs.user_summary(user["id"])["usd"],
                6,
            ),
        }
