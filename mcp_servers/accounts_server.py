"""Accounts MCP server: balances and credit card info (read-only)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP
from app import data

mcp = FastMCP("accounts")


@mcp.tool()
def list_accounts(user_id: str) -> str:
    """List all of the customer's bank accounts with type and balance (INR)."""
    c = data.conn()
    rows = c.execute("SELECT id,type,balance FROM accounts WHERE user_id=?", (user_id,)).fetchall()
    c.close()
    return json.dumps([dict(r) for r in rows])


@mcp.tool()
def get_balance(user_id: str, account_type: str = "savings") -> str:
    """Get the balance (INR) of the customer's account. account_type: 'savings' or 'current'."""
    c = data.conn()
    row = c.execute("SELECT id,type,balance FROM accounts WHERE user_id=? AND type=?",
                    (user_id, account_type.lower())).fetchone()
    c.close()
    if not row:
        return json.dumps({"error": f"No {account_type} account found for this customer"})
    return json.dumps({"account_id": row["id"], "type": row["type"], "balance_inr": row["balance"]})


@mcp.tool()
def get_credit_card_info(user_id: str) -> str:
    """Get the customer's current credit card limit (INR)."""
    c = data.conn()
    row = c.execute("SELECT credit_limit FROM credit_cards WHERE user_id=?", (user_id,)).fetchone()
    c.close()
    return json.dumps({"credit_limit_inr": row["credit_limit"]} if row else {"error": "No credit card"})


if __name__ == "__main__":
    mcp.run()
