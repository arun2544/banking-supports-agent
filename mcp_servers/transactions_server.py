"""Transactions MCP server: history, search and fraud flagging."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP
from app import data

mcp = FastMCP("transactions")

BASE = """SELECT t.id, t.ts, t.direction, t.amount, t.merchant, t.flagged, t.flag_reason
          FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE a.user_id=? """


@mcp.tool()
def get_recent_transactions(user_id: str, limit: int = 5) -> str:
    """Get the customer's most recent transactions (newest first). limit max 20."""
    limit = max(1, min(int(limit), 20))
    c = data.conn()
    rows = c.execute(BASE + "ORDER BY t.ts DESC LIMIT ?", (user_id, limit)).fetchall()
    c.close()
    return json.dumps([dict(r) for r in rows])


@mcp.tool()
def search_transactions(user_id: str, merchant: str) -> str:
    """Search the customer's transactions by merchant name."""
    c = data.conn()
    rows = c.execute(BASE + "AND t.merchant LIKE ? ORDER BY t.ts DESC LIMIT 20",
                     (user_id, f"%{merchant}%")).fetchall()
    c.close()
    return json.dumps([dict(r) for r in rows])


@mcp.tool()
def flag_transaction(user_id: str, transaction_id: str, reason: str = "suspicious") -> str:
    """Flag one of the customer's transactions as suspicious/fraudulent for review."""
    c = data.conn()
    owned = c.execute(BASE + "AND t.id=?", (user_id, transaction_id)).fetchone()
    if not owned:  # authorization: the transaction must belong to this customer
        c.close()
        return json.dumps({"status": "denied", "reason": "Transaction not found for this customer"})
    c.execute("UPDATE transactions SET flagged=1, flag_reason=? WHERE id=?", (reason[:200], transaction_id))
    c.commit()
    c.close()
    return json.dumps({"status": "flagged", "transaction_id": transaction_id})


@mcp.tool()
def get_flagged_transactions(user_id: str) -> str:
    """List transactions the customer has previously flagged."""
    c = data.conn()
    rows = c.execute(BASE + "AND t.flagged=1 ORDER BY t.ts DESC", (user_id,)).fetchall()
    c.close()
    return json.dumps([dict(r) for r in rows])


@mcp.tool()
def request_statement(user_id: str, account_type: str = "savings", months: int = 1) -> str:
    """Request an account statement for the last N months (1-12), sent to the registered email."""
    months = max(1, min(int(months), 12))
    c = data.conn()
    c.execute("INSERT INTO service_requests(user_id,kind,details,status) VALUES(?,?,?,?)",
              (user_id, "statement", f"{account_type}, {months} month(s)", "submitted"))
    c.commit(); c.close()
    return json.dumps({"status": "submitted", "account_type": account_type, "months": months})


if __name__ == "__main__":
    mcp.run()
