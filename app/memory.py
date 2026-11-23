"""Session Store: conversation history + inter-agent shared state. SQLite here; use Redis/Postgres in production.
Keyed by (user_id, session_id) so users can never read each other's sessions."""
import json, sqlite3, threading, uuid
from dataclasses import dataclass, field

from . import config


@dataclass
class Session:
    messages: list = field(default_factory=list)       # plain-text turns [{"role","content"}]
    shared_state: dict = field(default_factory=dict)   # facts agents hand to one another


class SessionStore:
    def __init__(self, path: str | None = None):
        self.path = path or config.SESSION_DB
        self._lock = threading.Lock()
        with self._db() as c:
            c.execute("CREATE TABLE IF NOT EXISTS sessions(user_id TEXT, session_id TEXT, data TEXT, "
                      "PRIMARY KEY(user_id, session_id))")

    def _db(self):
        return sqlite3.connect(self.path, timeout=10)

    def get(self, user_id: str, session_id: str | None) -> tuple[str, Session]:
        sid = session_id or uuid.uuid4().hex
        with self._lock, self._db() as c:
            row = c.execute("SELECT data FROM sessions WHERE user_id=? AND session_id=?", (user_id, sid)).fetchone()
        if row:
            d = json.loads(row[0])
            return sid, Session(d["messages"], d["shared_state"])
        return sid, Session()

    def save(self, user_id: str, session_id: str, s: Session):
        s.messages = s.messages[-config.MAX_HISTORY_MESSAGES:]
        with self._lock, self._db() as c:
            c.execute("INSERT OR REPLACE INTO sessions VALUES(?,?,?)",
                      (user_id, session_id, json.dumps({"messages": s.messages, "shared_state": s.shared_state})))

    def append_turn(self, s: Session, user_text: str, assistant_text: str):
        s.messages += [{"role": "user", "content": user_text}, {"role": "assistant", "content": assistant_text}]
