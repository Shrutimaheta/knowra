"""Verify Managed Auth JWTs and bind subjects to app-owned workspaces."""

import os
import secrets
from functools import lru_cache
from urllib.parse import urlsplit
from uuid import uuid4

import jwt
from app.security import password_hash, session
from app.store import db
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/auth")


def enabled():
    return os.getenv("AUTH_PROVIDER") == "neon"


@lru_cache(maxsize=2)
def jwks(url):
    return jwt.PyJWKClient(url, cache_keys=True, timeout=10)


def verify(token):
    base = urlsplit(os.environ["NEON_AUTH_BASE_URL"])
    issuer = base.scheme + "://" + base.netloc
    try:
        key = jwks(os.environ["NEON_AUTH_JWKS_URL"]).get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=["EdDSA"], issuer=issuer,
                            options={"require": ["sub", "exp", "iss"], "verify_aud": False})
        if not isinstance(claims["sub"], str) or len(claims["sub"]) > 200:
            raise ValueError
        return claims
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(401, "Neon session is invalid or expired. Please sign in again.") from None


class Exchange(BaseModel):
    token: str = Field(min_length=20, max_length=16000)
    workspace: str = Field(default="My knowledge workspace", min_length=1, max_length=100)


@router.post("/neon")
def exchange(body: Exchange, request: Request, response: Response):
    if not enabled():
        raise HTTPException(404, "Managed login is not enabled.")
    claims = verify(body.token)
    with db() as c:
        row = c.execute("SELECT u.* FROM users u JOIN external_identities i ON i.user_id=u.id WHERE i.provider='neon' AND i.subject=?", (claims["sub"],)).fetchone()
        if not row:
            # Never bind an existing local account merely because its email matches.
            user_id, org = str(uuid4()), str(uuid4())
            email = str(claims.get("email") or "")[:254]
            if not email or c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
                raise HTTPException(409, "This identity needs an explicit account migration. Contact the workspace owner.")
            name = str(claims.get("name") or "Neon member")[:100]
            c.execute("INSERT INTO organizations VALUES (?,?)", (org, body.workspace.strip() or "My knowledge workspace"))
            c.execute("INSERT INTO users VALUES (?,?,?,?,?,?)", (user_id, email, name, password_hash(secrets.token_urlsafe(40)), org, "owner"))
            c.execute("INSERT INTO external_identities VALUES ('neon',?,?)", (claims["sub"], user_id))
            row = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        session_token = session(c, row, response, request.headers.get("user-agent", "Browser"))
        # The app session must not outlive the verified upstream token.
        import time

        c.execute("UPDATE sessions SET expires=? WHERE token=?", (min(float(claims["exp"]), time.time() + 86400), session_token))
    return {"ok": True}
