"""Sign-in, registration, demo entry and the current user."""

import hashlib
import os

from app.demo import NOTICE as DEMO_NOTICE
from app.demo import enabled as demo_enabled
from app.demo import enter as enter_demo
from app.demo import public_dashboard as public_demo_dashboard
from app.embeddings import model_name
from app.neon_auth import enabled as neon_login
from app.providers import generation_provider
from app.routes.common import Credentials, Registration, audit, uid
from app.routes.documents import documents
from app.routes.workspace import analytics_summary
from app.security import (
    LOCKED_MESSAGE,
    clear_login_failures,
    current_user,
    login_locked,
    password_hash,
    record_login_failure,
    session,
    verify_password,
)
from app.store import db
from fastapi import APIRouter, Depends, HTTPException, Request, Response

router = APIRouter()


@router.get("/api/v1/app-config")
def app_config():
    return {"demo": demo_enabled(), "public_dashboard": public_demo_dashboard(), "notice": DEMO_NOTICE if demo_enabled() else "", "login_email": "demo@knowra.example" if demo_enabled() else "", "auth_provider": "neon" if neon_login() else "local", "auth_url": os.getenv("NEON_AUTH_BASE_URL") if neon_login() else None}


@router.post("/api/v1/auth/demo")
def demo_entry(request: Request, response: Response, dashboard: bool = False):
    result = enter_demo(request, response, include_user=dashboard)
    if not dashboard:
        return result
    # Reuse the just-validated visitor; no extra browser authentication round trip.
    visitor = result["user"]
    visible = documents(visitor)
    return {"user": me(visitor), "documents": visible, "analytics": analytics_summary(visitor, visible)}


@router.post("/api/v1/auth/register", status_code=201)
def register(body: Registration, response: Response, request: Request):
    if neon_login():
        raise HTTPException(409, "Use the managed Neon sign-up form.")
    email = body.email.strip().lower()
    if "@" not in email or not body.name.strip() or not body.workspace.strip():
        raise HTTPException(422, "Enter a valid email, name, and workspace.")
    with db() as c:
        if c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            raise HTTPException(409, "An account with this email already exists.")
        user = {
            "id": uid(),
            "email": email,
            "name": body.name.strip(),
            "password": password_hash(body.password),
            "org": uid(),
            "role": "owner",
        }
        c.execute(
            "INSERT INTO organizations VALUES (?,?)",
            (user["org"], body.workspace.strip()),
        )
        c.execute(
            "INSERT INTO users (id,email,name,password,org,role) VALUES (:id,:email,:name,:password,:org,:role)",
            user,
        )
        session(c, user, response, request.headers.get("user-agent", "Browser"))
        audit(c, user, "workspace.created", user["org"])
    return {"id": user["id"]}


@router.post("/api/v1/auth/login")
def login(body: Credentials, response: Response, request: Request):
    if neon_login():
        raise HTTPException(409, "Use the managed Neon sign-in form.")
    email = body.email.strip().lower()
    with db() as c:
        if login_locked(c, email):
            raise HTTPException(429, LOCKED_MESSAGE, headers={"Retry-After": "900"})
        row = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        stored = row["password"] if row else password_hash("dummy password")
        # Always verify (dummy hash for unknown emails) so timing reveals nothing.
        valid = verify_password(body.password, stored) and bool(row)
        if valid:
            clear_login_failures(c, email)
            if not stored.startswith("$argon2"):
                c.execute(
                    "UPDATE users SET password=? WHERE id=?",
                    (password_hash(body.password), row["id"]),
                )
            session(c, row, response, request.headers.get("user-agent", "Browser"))
            return {"ok": True}
        # Commit the failure before raising: an exception inside the block rolls back.
        locked = record_login_failure(c, email)
    if locked:
        raise HTTPException(429, LOCKED_MESSAGE, headers={"Retry-After": "900"})
    raise HTTPException(401, "Email or password is incorrect.")


@router.post("/api/v1/auth/logout")
def logout(request: Request, response: Response, user=Depends(current_user)):
    with db() as c:
        c.execute(
            "DELETE FROM sessions WHERE token=?",
            (hashlib.sha256(request.cookies["knowra_session"].encode()).hexdigest(),),
        )
    response.delete_cookie("knowra_session")
    return {"ok": True}


@router.get("/api/v1/users/me")
def me(user=Depends(current_user)):
    provider = generation_provider()
    with db() as c:
        workspace = c.execute(
            "SELECT name FROM organizations WHERE id=?", (user["org"],)
        ).fetchone()["name"]
    return {k: v for k, v in user.items() if k != "password"} | {
        "workspace": workspace,
        "mode": "AI synthesis" if provider else "Evidence only",
        "provider": provider.name if provider else "evidence",
        "generation_model": provider.model if provider else None,
        "retrieval": "Hybrid semantic + keyword" if model_name() else "Keyword",
        "embedding_model": model_name() or None,
        "demo": demo_enabled(),
        "source_integrity": bool(os.getenv("NEON_FUNCTION_HELLO_BASE_URL") and os.getenv("KNOWRA_FUNCTION_SECRET")),
    }
