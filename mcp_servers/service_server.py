"""Service MCP server: change of address, cheque book request, KYC update, credit limit. Enforces RBAC + confirmations."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP
from app import data
from app.policy import authorize, MAX_LIMIT_BY_TIER

mcp = FastMCP("service")


def _record(c, user_id, kind, details):
    c.execute("INSERT INTO service_requests(user_id,kind,details,status) VALUES(?,?,?,?)",
              (user_id, kind, details, "submitted"))


@mcp.tool()
def get_registered_address(user_id: str) -> str:
    """Get the customer's registered address (use it to ask the customer to confirm before address-dependent requests)."""
    return json.dumps({"registered_address": data.get_user(user_id)["address"]})


@mcp.tool()
def update_address(user_id: str, new_address: str, customer_confirmed: bool = False) -> str:
    """Change the registered address. Only call with customer_confirmed=true after the customer explicitly confirmed the new address."""
    if not customer_confirmed:
        return json.dumps({"status": "needs_confirmation", "message": "Ask the customer to confirm the new address first."})
    c = data.conn()
    c.execute("UPDATE users SET address=? WHERE id=?", (new_address[:300], user_id))
    _record(c, user_id, "address_change", new_address[:300])
    c.commit(); c.close()
    return json.dumps({"status": "updated"})


@mcp.tool()
def request_cheque_book(user_id: str, address_confirmed: bool = False) -> str:
    """Submit a cheque book request to the registered address. Call with address_confirmed=true ONLY after the customer confirmed the delivery address."""
    if not address_confirmed:
        addr = data.get_user(user_id)["address"]
        return json.dumps({"status": "needs_confirmation",
                           "message": f"Confirm the delivery address with the customer first: {addr}"})
    c = data.conn()
    _record(c, user_id, "cheque_book", data.get_user(user_id)["address"])
    c.commit(); c.close()
    return json.dumps({"status": "submitted"})


@mcp.tool()
def increase_credit_limit(user_id: str, new_limit: float) -> str:
    """Increase the customer's credit card limit (INR). Premium customers only."""
    user = data.get_user(user_id)
    if not authorize(user["tier"], "increase_credit_limit"):
        return json.dumps({"status": "denied", "reason": "Your account tier does not have permission to increase the credit limit."})
    cap = MAX_LIMIT_BY_TIER[user["tier"]]
    c = data.conn()
    current = c.execute("SELECT credit_limit FROM credit_cards WHERE user_id=?", (user_id,)).fetchone()["credit_limit"]
    if new_limit <= current:
        c.close()
        return json.dumps({"status": "rejected", "reason": f"New limit must exceed current limit {current}"})
    if new_limit > cap:
        c.close()
        return json.dumps({"status": "rejected", "reason": f"Maximum allowed limit for your tier is {cap}"})
    c.execute("UPDATE credit_cards SET credit_limit=? WHERE user_id=?", (new_limit, user_id))
    _record(c, user_id, "credit_limit_increase", f"{current} -> {new_limit}")
    c.commit(); c.close()
    return json.dumps({"status": "increased", "old_limit": current, "new_limit": new_limit})


@mcp.tool()
def update_kyc(user_id: str, document_type: str, document_last4: str, customer_confirmed: bool = False) -> str:
    """Start a KYC update. document_type: aadhaar, pan, passport, voter_id or driving_licence. Pass ONLY the last 4 characters of the document number (never the full number). Call with customer_confirmed=true only after the customer confirmed the details."""
    allowed = {"aadhaar", "pan", "passport", "voter_id", "driving_licence"}
    if document_type.lower() not in allowed:
        return json.dumps({"status": "rejected", "reason": f"document_type must be one of {sorted(allowed)}"})
    if len(document_last4) != 4:
        return json.dumps({"status": "rejected", "reason": "Provide only the last 4 characters of the document number."})
    if not customer_confirmed:
        return json.dumps({"status": "needs_confirmation", "message": "Ask the customer to confirm the KYC document type and last 4 characters."})
    c = data.conn()
    _record(c, user_id, "kyc_update", f"{document_type.lower()} ****{document_last4}")
    c.commit(); c.close()
    return json.dumps({"status": "submitted", "next": "Customer will be asked to upload the document in the app for verification."})


if __name__ == "__main__":
    mcp.run()
