"""Token-based authentication (JWT). Swap `authenticate` for your real IdP (OIDC / Keycloak / Okta)."""
import time
import jwt
from fastapi import HTTPException

from . import config, data


def authenticate(username: str, password: str) -> dict | None:
    row = data.get_user_by_username(username)
    if row and data.verify_password(password, row["password_hash"]):
        return {"id": row["id"], "name": row["name"], "tier": row["tier"]}
    return None


def create_token(user: dict) -> str:
    now = int(time.time())
    payload = {"sub": user["id"], "name": user["name"], "tier": user["tier"],
               "iat": now, "exp": now + config.JWT_TTL_MIN * 60}
    return jwt.encode(payload, config.JWT_SECRET, algorithm="HS256")


def verify_token(token: str) -> dict:
    try:
        p = jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    row = data.get_user(p["sub"])
    if not row:
        raise HTTPException(status_code=401, detail="Unknown user")
    # tier comes from the DB, not from the token, so demotions take effect immediately
    return {"id": row["id"], "name": row["name"], "tier": row["tier"]}
