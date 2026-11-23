"""Cost tracker: tokens and USD per user / agent / provider."""
import threading
from collections import defaultdict

from . import config
from .observability import metrics

_PRICES = {  # provider -> (USD per 1M input tokens, USD per 1M output tokens)
    "third_party": (config.THIRD_PARTY_PRICE_IN, config.THIRD_PARTY_PRICE_OUT),
    "self_hosted": (config.SELF_HOSTED_PRICE_IN, config.SELF_HOSTED_PRICE_OUT),
}


class CostTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self.by_user = defaultdict(lambda: {"input_tokens": 0, "output_tokens": 0, "usd": 0.0})
        self.by_key = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "usd": 0.0})

    def record(self, user_id: str, agent: str, r) -> float:
        p_in, p_out = _PRICES[r.provider]
        usd = (r.input_tokens * p_in + r.output_tokens * p_out) / 1_000_000
        with self._lock:
            u = self.by_user[user_id]
            u["input_tokens"] += r.input_tokens; u["output_tokens"] += r.output_tokens; u["usd"] += usd
            k = self.by_key[f"{agent}|{r.provider}|{r.model}"]
            k["calls"] += 1; k["input_tokens"] += r.input_tokens; k["output_tokens"] += r.output_tokens; k["usd"] += usd
        return usd

    def user_summary(self, user_id: str) -> dict:
        with self._lock:
            return dict(self.by_user[user_id])

    def render(self) -> str:
        lines = []
        with self._lock:
            for key, v in sorted(self.by_key.items()):
                agent, provider, model = key.split("|")
                lab = f'{{agent="{agent}",provider="{provider}",model="{model}"}}'
                lines += [f"llm_calls{lab} {v['calls']}", f"llm_input_tokens{lab} {v['input_tokens']}",
                          f"llm_output_tokens{lab} {v['output_tokens']}", f"llm_cost_usd{lab} {v['usd']:.6f}"]
        return "\n".join(lines) + "\n"
