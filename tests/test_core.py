import os, tempfile
os.environ["BANK_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")

from app import auth, data, policy
from app.pii import redact


def test_card_redacted_but_amounts_kept():
    t, f = redact("card 4111 1111 1111 1111 balance 52340")
    assert "4111" not in t and "52340" in t and "CREDIT_CARD" in f


def test_other_pii():
    t, f = redact("mail a@b.com pan ABCDE1234F phone 9876543210")
    assert "[EMAIL]" in t and "[PAN]" in t and "[PHONE]" in t


def test_login_and_token():
    data.init_db(reset=True)
    assert auth.authenticate("alice", "wrong") is None
    u = auth.authenticate("alice", "alice123")
    assert auth.verify_token(auth.create_token(u))["tier"] == "premium"


def test_rbac():
    assert policy.authorize("premium", "increase_credit_limit")
    assert not policy.authorize("standard", "increase_credit_limit")


# ---- router / cost / session store ----
import asyncio, types
from app.llm_router import LLMRouter, SelfHostedProvider, LLMResult
from app.cost_tracker import CostTracker
from app.memory import SessionStore


class _P:  # stand-in provider
    def __init__(self, name): self.name = name


def test_router_policy():
    tp, sh = _P("third_party"), _P("self_hosted")
    r = LLMRouter(third_party=tp, self_hosted=sh)
    assert r.choose("subagent", False) is sh          # raw banking data stays self-hosted
    assert r.choose("coordinator", False) is tp       # complex reasoning -> third party
    assert r.choose("coordinator", True) is sh        # PII in turn -> self-hosted
    r2 = LLMRouter(third_party=tp, self_hosted=None)
    assert r2.choose("subagent", True) is tp          # no self-hosted configured -> fallback


def test_openai_message_conversion():
    msgs = [{"role": "user", "content": "hi"},
            {"role": "assistant", "content": [{"type": "text", "text": "ok"},
                                              {"type": "tool_use", "id": "1", "name": "get_balance", "input": {"account_type": "savings"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "1", "content": "{\"b\":1}"}]}]
    out = SelfHostedProvider._convert("sys", msgs)
    assert out[0]["role"] == "system" and out[2]["tool_calls"][0]["function"]["name"] == "get_balance"
    assert out[3] == {"role": "tool", "tool_call_id": "1", "content": "{\"b\":1}"}


def test_cost_tracker():
    c = CostTracker()
    usd = c.record("u1", "coordinator", LLMResult("", [], 1_000_000, 1_000_000, "third_party", "m"))
    assert usd > 0 and c.user_summary("u1")["output_tokens"] == 1_000_000
    assert c.record("u1", "accounts", LLMResult("", [], 500, 500, "self_hosted", "l")) == 0


def test_session_store_persists_and_isolates(tmp_path):
    st = SessionStore(str(tmp_path / "s.db"))
    sid, s = st.get("u1", None)
    st.append_turn(s, "hello", "hi"); st.save("u1", sid, s)
    assert SessionStore(str(tmp_path / "s.db")).get("u1", sid)[1].messages[0]["content"] == "hello"
    assert st.get("u2", sid)[1].messages == []          # another user can't see it
