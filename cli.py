"""Tiny terminal client:  python cli.py   (server must be running)"""
import getpass, httpx

BASE = "http://127.0.0.1:8000"
u = input("username (alice/bob): ")
r = httpx.post(f"{BASE}/auth/login", json={"username": u, "password": getpass.getpass("password: ")})
r.raise_for_status()
headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
sid = None
print("Logged in. Type 'quit' to exit.")
while (q := input("\nyou> ").strip()) not in ("quit", "exit"):
    resp = httpx.post(f"{BASE}/chat", json={"message": q, "session_id": sid}, headers=headers, timeout=120)
    if resp.status_code != 200:
        print("error:", resp.text); continue
    d = resp.json(); sid = d["session_id"]
    print(f"\nbot [{', '.join(d['agents_called']) or 'no agents'}]> {d['reply']}")
