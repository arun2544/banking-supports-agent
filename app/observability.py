"""Structured JSON logs, request-scoped trace ids, spans and Prometheus-style metrics."""
import contextvars, json, logging, threading, time
from contextlib import contextmanager

from .pii import redact

request_id_var = contextvars.ContextVar("request_id", default="-")
logger = logging.getLogger("bank-agent")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


class Metrics:
    def __init__(self):
        self._lock = threading.Lock()
        self.counters: dict[str, float] = {}
        self.hist: dict[str, list[float]] = {}  # key -> [count, sum]

    def inc(self, name: str, **labels):
        key = self._key(name, labels)
        with self._lock:
            self.counters[key] = self.counters.get(key, 0) + 1

    def observe(self, name: str, value: float, **labels):
        key = self._key(name, labels)
        with self._lock:
            c = self.hist.setdefault(key, [0, 0.0])
            c[0] += 1
            c[1] += value

    @staticmethod
    def _key(name, labels):
        if not labels:
            return name
        return name + "{" + ",".join(f'{k}="{v}"' for k, v in sorted(labels.items())) + "}"

    def render(self) -> str:
        lines = []
        with self._lock:
            for k, v in sorted(self.counters.items()):
                lines.append(f"{k} {v}")
            for k, (cnt, total) in sorted(self.hist.items()):
                base, _, lab = k.partition("{")
                lab = "{" + lab if lab else ""
                lines.append(f"{base}_count{lab} {cnt}")
                lines.append(f"{base}_sum{lab} {total:.6f}")
        return "\n".join(lines) + "\n"


metrics = Metrics()


def log(event: str, **fields):
    payload = {"ts": round(time.time(), 3), "request_id": request_id_var.get(), "event": event, **fields}
    logger.info(redact(json.dumps(payload, default=str))[0])


@contextmanager
def span(name: str, **attrs):
    start = time.perf_counter()
    status = "ok"
    try:
        yield
    except Exception as e:
        status = "error"
        attrs["error"] = type(e).__name__
        raise
    finally:
        dur = time.perf_counter() - start
        metrics.observe("agent_span_seconds", dur, span=name)
        metrics.inc("agent_span_total", span=name, status=status)
        log("span", span=name, duration_ms=round(dur * 1000, 1), status=status, **attrs)


def system_metrics() -> str:
    """CPU / memory / disk utilisation (diagram: Observability -> infrastructure)."""
    try:
        import psutil
    except ImportError:
        return ""
    vm, du = psutil.virtual_memory(), psutil.disk_usage("/")
    return (f"system_cpu_percent {psutil.cpu_percent(interval=None)}\n"
            f"system_memory_percent {vm.percent}\nsystem_memory_used_bytes {vm.used}\n"
            f"system_disk_percent {du.percent}\nsystem_disk_used_bytes {du.used}\n")
