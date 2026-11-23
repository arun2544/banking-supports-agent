import logging
import time, uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from . import auth, config, data
from .agents import Orchestrator
import os
from .cost_tracker import CostTracker
from .llm_router import LLMRouter
from .mcp_client import MCPHub
from .memory import SessionStore
from .observability import log, metrics, request_id_var, system_metrics

logger = logging.getLogger("banking_agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    data.init_db()
    hub = MCPHub()
    await hub.start()
    app.state.hub = hub
    app.state.costs = CostTracker()
    app.state.orch = Orchestrator(LLMRouter(), hub, SessionStore(), app.state.costs)
    yield
    await hub.stop()


app = FastAPI(title="Banking Support Agent", lifespan=lifespan)
bearer = HTTPBearer(auto_error=False)
_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(key: str, limit: int):
    now, q = time.time(), _hits[key]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= limit:
        metrics.inc("rate_limited_total")
        raise HTTPException(status_code=429, detail="Too many requests. Please slow down.")
    q.append(now)


@app.middleware("http")
async def edge(request: Request, call_next):
    request_id_var.set(request.headers.get("x-request-id") or uuid.uuid4().hex[:12])
    start = time.perf_counter()

    try:
        resp = await call_next(request)
    except Exception:
        metrics.inc("http_errors_total")
        logger.exception("Unhandled exception on %s", request.url.path)
        log("unhandled_error", path=request.url.path)
        resp = JSONResponse({"detail": "Internal error"}, status_code=500)

    resp.headers.update({
        "X-Request-ID": request_id_var.get(),
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Cache-Control": "no-store",
        "Content-Security-Policy": (
            "default-src 'self'; connect-src 'self'; frame-ancestors 'none'"
            if request.url.path.startswith("/ui") else "default-src 'none'"
        ),
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains"
    })

    # Explicit UTF-8 charset for JSON responses, including Windows PowerShell 5.1
    content_type = resp.headers.get("content-type", "")
    if content_type.startswith("application/json") and "charset=" not in content_type.lower():
        resp.headers["content-type"] = "application/json; charset=utf-8"

    metrics.inc("http_requests_total", path=request.url.path, status=resp.status_code)
    metrics.observe("http_request_seconds", time.perf_counter() - start, path=request.url.path)

    return resp


def current_user(cred: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    if not cred:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return auth.verify_token(cred.credentials)


class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=128)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, max_length=64)


@app.post("/auth/login")
def login(body: LoginIn, request: Request):
    rate_limit(f"login:{request.client.host}", config.LOGIN_RATE_LIMIT_PER_MIN)
    user = auth.authenticate(body.username, body.password)
    if not user:
        metrics.inc("login_failures_total")
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {
        "access_token": auth.create_token(user),
        "token_type": "bearer",
        "tier": user["tier"]
    }


@app.post("/chat")
async def chat(body: ChatIn, request: Request, user: dict = Depends(current_user)):
    rate_limit(f"chat:{user['id']}", config.RATE_LIMIT_PER_MIN)
    return await request.app.state.orch.chat(user, body.session_id, body.message)


@app.get("/costs")
def costs(request: Request, user: dict = Depends(current_user)):
    return request.app.state.costs.user_summary(user["id"])


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/ui/index.html")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/metrics", response_class=PlainTextResponse)
def prom(request: Request):
    return metrics.render() + system_metrics() + request.app.state.costs.render()


app.mount(
    "/ui",
    StaticFiles(
        directory=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "static"
        )
    ),
    name="ui"
)