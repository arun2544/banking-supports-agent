"""Mock core-banking database (SQLite). Shared by all MCP server processes."""
import hashlib, hmac, os, secrets, sqlite3

DB_PATH = os.getenv("BANK_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bank.db"))


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def hash_password(pw: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${h}"


def verify_password(pw: str, stored: str) -> bool:
    salt = stored.split("$")[0]
    return hmac.compare_digest(hash_password(pw, salt), stored)


SCHEMA = """
CREATE TABLE users(id TEXT PRIMARY KEY, username TEXT UNIQUE, name TEXT, password_hash TEXT,
                   tier TEXT, address TEXT);
CREATE TABLE accounts(id TEXT PRIMARY KEY, user_id TEXT, type TEXT, balance REAL);
CREATE TABLE transactions(id TEXT PRIMARY KEY, account_id TEXT, ts TEXT, direction TEXT,
                          amount REAL, merchant TEXT, flagged INTEGER DEFAULT 0, flag_reason TEXT);
CREATE TABLE credit_cards(user_id TEXT PRIMARY KEY, credit_limit REAL);
CREATE TABLE service_requests(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, kind TEXT,
                              details TEXT, status TEXT, ts TEXT DEFAULT CURRENT_TIMESTAMP);
"""


def init_db(reset: bool = False) -> None:
    if os.path.exists(DB_PATH) and not reset:
        return
    c = conn()
    for t in ("users", "accounts", "transactions", "credit_cards", "service_requests"):
        c.execute(f"DROP TABLE IF EXISTS {t}")
    c.executescript(SCHEMA)
    c.executemany("INSERT INTO users VALUES(?,?,?,?,?,?)", [
        ("u1", "alice", "Alice Sharma", hash_password("alice123"), "premium", "12 MG Road, Varanasi 221001"),
        ("u2", "bob", "Bob Verma", hash_password("bob123"), "standard", "7 Park Street, Lucknow 226001"),
    ])
    c.executemany("INSERT INTO accounts VALUES(?,?,?,?)", [
        ("A1", "u1", "savings", 52340.00),
        ("A2", "u1", "current", 18200.00),
        ("A3", "u2", "savings", 24345.00),
    ])
    c.executemany("INSERT INTO transactions(id,account_id,ts,direction,amount,merchant) VALUES(?,?,?,?,?,?)", [
        ("T1001", "A1", "2026-11-22 10:15", "debit", 4200, "Amazon"),
        ("T1002", "A1", "2026-11-21 19:40", "debit", 850, "Swiggy"),
        ("T1003", "A1", "2026-11-20 09:00", "credit", 75000, "Salary - Acme Corp"),
        ("T1004", "A1", "2026-11-18 14:22", "debit", 12999, "Flipkart"),
        ("T1005", "A1", "2026-11-17 08:05", "debit", 1500, "Uber"),
        ("T1006", "A1", "2026-11-15 21:30", "debit", 3200, "Zomato"),
        ("T2001", "A3", "2026-11-22 12:00", "debit", 560, "BigBasket"),
        ("T2002", "A3", "2026-11-20 09:00", "credit", 25000, "Salary - Globex"),
    ])
    c.executemany("INSERT INTO credit_cards VALUES(?,?)", [("u1", 200000), ("u2", 50000)])
    c.commit()
    c.close()


def get_user(user_id: str):
    c = conn()
    row = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    c.close()
    return row


def get_user_by_username(username: str):
    c = conn()
    row = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    c.close()
    return row
