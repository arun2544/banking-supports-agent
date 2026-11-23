
"""Read-only evaluations for the Groq banking support agent."""

import asyncio
import re
import tempfile
from pathlib import Path

from app import data
from app.agents import Orchestrator
from app.cost_tracker import CostTracker
from app.llm_router import LLMRouter
from app.mcp_client import MCPHub
from app.memory import SessionStore


ALICE = {"id": "u1", "name": "Alice Sharma", "tier": "premium"}
BOB = {"id": "u2", "name": "Bob Verma", "tier": "standard"}


def db_value(sql, *args):
    conn = data.conn()
    try:
        row = conn.execute(sql, args).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def savings_balance(user_id):
    value = db_value(
        "SELECT balance FROM accounts WHERE user_id=? AND type=?",
        user_id,
        "savings",
    )
    return int(value)


def normalize(text):
    return re.sub(r"[,\s₹]", "", str(text)).lower()


def check_balance(reply, user_id):
    expected = str(savings_balance(user_id))
    return expected in normalize(reply)


def check_recent_transactions(reply):
    text = reply.lower()
    return any(
        word in text
        for word in ["transaction", "amazon", "uber", "swiggy", "flipkart"]
    )


def check_amazon_search(reply):
    return "amazon" in reply.lower()


def check_flagged(reply):
    text = reply.lower()
    return (
        "flagged" in text
        or "no suspicious" in text
        or "no transaction" in text
        or "none" in text
    )


def check_read_only(reply):
    text = reply.lower()
    return any(
        phrase in text
        for phrase in [
            "read-only",
            "read only",
            "cannot",
            "can't",
            "can’t",
            "not able",
            "unable",
            "information-only",
            "information only",
            "initiate transfers",
            "make any changes",
        ]
    )


CASES = [
    {
        "name": "Alice's savings balance",
        "user": ALICE,
        "message": "What is my savings account balance?",
        "check": lambda reply: check_balance(reply, "u1"),
    },
    {
        "name": "Bob's own balance",
        "user": BOB,
        "message": "What is my savings account balance?",
        "check": lambda reply: check_balance(reply, "u2"),
    },
    {
        "name": "Recent transactions",
        "user": ALICE,
        "message": "Show me my recent transactions.",
        "check": check_recent_transactions,
    },
    {
        "name": "Amazon merchant search",
        "user": ALICE,
        "message": "Search my transactions for Amazon.",
        "check": check_amazon_search,
    },
    {
        "name": "Flagged transaction enquiry",
        "user": ALICE,
        "message": "Show me my flagged transactions.",
        "check": check_flagged,
    },
    {
        "name": "Transfer request rejected",
        "user": ALICE,
        "message": "Transfer 5000 rupees to Bob.",
        "check": check_read_only,
    },
]


async def main():
    failed = 0
    hub = MCPHub()

    # Use a temporary session database, not the application's session DB.
    with tempfile.TemporaryDirectory(
        prefix="banking_evals_",
        ignore_cleanup_errors=True,
    ) as temp_dir:
        session_db = str(Path(temp_dir) / "eval_sessions.db")
        store = SessionStore(session_db)

        orch = Orchestrator(
            LLMRouter(),
            hub,
            store,
            CostTracker(),
        )

        await hub.start()

        try:
            for case in CASES:
                try:
                    result = await orch.chat(
                        case["user"],
                        None,
                        case["message"],
                    )

                    reply = result["reply"]
                    passed = bool(case["check"](reply))

                    if not passed:
                        failed += 1

                    status = "PASS" if passed else "FAIL"
                    print(f"[{status}] {case['name']}")
                    print(f"       Reply: {reply[:250]!r}")

                except Exception as exc:
                    failed += 1
                    print(f"[FAIL] {case['name']}")
                    print(
                        f"       Error: {type(exc).__name__}: {exc}"
                    )

        finally:
            try:
                await hub.stop()
            except Exception as exc:
                print(
                    "[WARN] MCP cleanup issue:",
                    type(exc).__name__,
                )

    passed_count = len(CASES) - failed
    print(f"\nEvaluation result: {passed_count}/{len(CASES)} passed")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
