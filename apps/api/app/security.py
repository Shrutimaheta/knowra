"""Account recovery, invitations and revocable sessions. Raw tokens are never stored."""

import hashlib
import hmac
import logging
import os
import re
import secrets
import smtplib
import time
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from uuid import uuid4

from app.store import db
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

router = APIRouter(prefix="/api/v1")
_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


def digest(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def password_hash(password):
    return _hasher.hash(password)


def verify_password(password, stored):
    if stored.startswith("$argon2"):
        try:
            return _hasher.verify(stored, password)
        except (VerificationError, InvalidHashError):
            return False
    try:
        salt, expected = stored.split(":", 1)
        actual = hashlib.scrypt(
            password.encode(), salt=salt.encode(), n=16384, r=8, p=1
        ).hex()
        return hmac.compare_digest(actual, expected)
    except ValueError:
        return False


def current_user(request: Request):
    with db() as c:
        user = c.execute(
            "SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires>?",
            (digest(request.cookies.get("knowra_session", "")), time.time()),
        ).fetchone()
    if not user:
        raise HTTPException(401, "Please sign in to continue.")
    return dict(user)


def admin(user=Depends(current_user)):
    if user["role"] not in ("owner", "admin"):
        raise HTTPException(403, "Workspace administrator access required.")
    return user


def session(c, user, response, agent="Browser"):
    token = secrets.token_urlsafe(32)
    c.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
    c.execute(
        "INSERT INTO sessions (token,user_id,expires,created,agent) VALUES (?,?,?,?,?)",
        (
            digest(token),
            user["id"],
            time.time() + 86400,
            datetime.now(UTC).isoformat(),
            agent[:250],
        ),
    )
    response.set_cookie(
        "knowra_session",
        token,
        httponly=True,
        secure=os.getenv("COOKIE_SECURE") == "true",
        samesite="strict",
        max_age=86400,
    )
    return digest(token)


def audit(c, user, action, target):
    c.execute(
        "INSERT INTO audit VALUES (?,?,?,?,?,?)",
        (
            str(uuid4()),
            user["org"],
            user["id"],
            action,
            target,
            datetime.now(UTC).isoformat(),
        ),
    )


def issue_token(c, kind, user_id=None, org=None, email=None, role=None):
    raw = secrets.token_urlsafe(32)
    c.execute(
        "INSERT INTO account_tokens (token,kind,user_id,org,email,role,expires,used) VALUES (?,?,?,?,?,?,?,0)",
        (
            digest(raw),
            kind,
            user_id,
            org,
            email,
            role,
            time.time() + (1800 if kind == "reset" else 86400),
        ),
    )
    return raw


def consume(c, token, kind):
    row = c.execute(
        "UPDATE account_tokens SET used=1 WHERE token=? AND kind=? AND used=0 AND expires>? RETURNING *",
        (digest(token), kind, time.time()),
    ).fetchone()
    if not row:
        raise HTTPException(
            400, "This link has expired or has already been used. Request a new one."
        )
    return row


def deliver(email, subject, body):
    message = EmailMessage()
    message["To"] = email
    message["From"] = os.getenv("SMTP_FROM", "knowra@localhost")
    message["Subject"] = subject
    message.set_content(body)
    if os.getenv("SMTP_HOST"):
        with smtplib.SMTP(
            os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587")), timeout=15
        ) as smtp:
            smtp.starttls()
            if os.getenv("SMTP_USER"):
                smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            smtp.send_message(message)
    elif os.getenv("APP_ENV", "development") == "development":
        directory = Path(os.getenv("MAIL_OUTBOX", "data/mail-outbox"))
        directory.mkdir(parents=True, exist_ok=True)
        (directory / (str(uuid4()) + ".eml")).write_text(
            message.as_string(), encoding="utf-8"
        )
    else:
        raise RuntimeError("SMTP is required outside development")


class EmailRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value.strip()):
            raise ValueError("Enter a valid email address")
        return value.strip().lower()


class RecoveryDeliveryError(Exception):
    pass


@router.post("/auth/forgot-password")
def forgot(body: EmailRequest):
    email = body.email.strip().lower()
    try:
        with db() as c:
            user = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if user:
                c.execute(
                    "DELETE FROM account_tokens WHERE user_id=? AND kind='reset'",
                    (user["id"],),
                )
                raw = issue_token(c, "reset", user_id=user["id"])
                link = (
                    os.getenv("PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")
                    + "/#reset="
                    + raw
                )
                try:
                    deliver(
                        email,
                        "Reset your Knowra password",
                        "Use this link within 30 minutes. It works once.\n\n" + link,
                    )
                except Exception as error:
                    raise RecoveryDeliveryError from error
    except RecoveryDeliveryError:
        # Same public response even during mail outages prevents email enumeration.
        # The exception exits the transaction, rolling back the undelivered token.
        logging.getLogger("knowra.mail").error(
            "Password recovery delivery failed; check SMTP configuration"
        )
    return {
        "message": "If an account exists, password recovery instructions have been sent."
    }


class Reset(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=10, max_length=128)


@router.post("/auth/reset-password")
def reset(body: Reset, response: Response):
    with db() as c:
        token = consume(c, body.token, "reset")
        c.execute(
            "UPDATE users SET password=? WHERE id=?",
            (password_hash(body.password), token["user_id"]),
        )
        c.execute("DELETE FROM sessions WHERE user_id=?", (token["user_id"],))
        c.execute(
            "DELETE FROM account_tokens WHERE user_id=? AND kind='reset'",
            (token["user_id"],),
        )
        user = c.execute(
            "SELECT * FROM users WHERE id=?", (token["user_id"],)
        ).fetchone()
        audit(c, user, "account.password_reset", user["id"])
    response.delete_cookie("knowra_session")
    return {"ok": True}


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


@router.post("/auth/change-password")
def change_password(
    body: PasswordChange, response: Response, user=Depends(current_user)
):
    if not verify_password(body.current_password, user["password"]):
        raise HTTPException(400, "Your current password is incorrect.")
    with db() as c:
        c.execute(
            "UPDATE users SET password=? WHERE id=?",
            (password_hash(body.new_password), user["id"]),
        )
        c.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
        c.execute("DELETE FROM account_tokens WHERE user_id=?", (user["id"],))
        session(c, user, response)
        audit(c, user, "account.password_changed", user["id"])
    return {"ok": True}


@router.get("/auth/sessions")
def sessions(request: Request, user=Depends(current_user)):
    current = digest(request.cookies.get("knowra_session", ""))
    with db() as c:
        return [
            {
                "id": r["token"],
                "created": r["created"],
                "agent": r["agent"] or "Earlier session",
                "expires": r["expires"],
                "current": r["token"] == current,
            }
            for r in c.execute(
                "SELECT * FROM sessions WHERE user_id=? AND expires>? ORDER BY expires DESC",
                (user["id"], time.time()),
            )
        ]


@router.delete("/auth/sessions/{session_id}")
def revoke(session_id: str, user=Depends(current_user)):
    with db() as c:
        c.execute(
            "DELETE FROM sessions WHERE token=? AND user_id=?", (session_id, user["id"])
        )
        audit(c, user, "account.session_revoked", user["id"])
    return {"ok": True}


class Invitation(EmailRequest):
    role: str = "member"


@router.post("/invitations", status_code=201)
def invite(body: Invitation, user=Depends(admin)):
    email = body.email.strip().lower()
    if "@" not in email or body.role not in ("viewer", "member", "admin"):
        raise HTTPException(422, "Enter a valid email and role.")
    with db() as c:
        if c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            raise HTTPException(409, "This email already has an account.")
        c.execute(
            "DELETE FROM account_tokens WHERE email=? AND org=? AND kind='invite'",
            (email, user["org"]),
        )
        raw = issue_token(c, "invite", org=user["org"], email=email, role=body.role)
        link = (
            os.getenv("PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")
            + "/#invite="
            + raw
        )
        try:
            deliver(
                email,
                "Join your Knowra workspace",
                "Your workspace administrator invited you. This link expires in 24 hours.\n\n"
                + link,
            )
        except Exception:
            raise HTTPException(503, "Invitation delivery is unavailable.") from None
        audit(c, user, "member.invited", email)
    return {
        "ok": True,
        "message": "Invitation sent. In development, find it in the local mail outbox.",
    }


class AcceptInvitation(Reset):
    name: str = Field(min_length=1, max_length=100)


@router.post("/invitations/accept", status_code=201)
def accept(body: AcceptInvitation, response: Response):
    if not body.name.strip():
        raise HTTPException(422, "Enter your name.")
    with db() as c:
        token = consume(c, body.token, "invite")
        if c.execute(
            "SELECT id FROM users WHERE email=?", (token["email"],)
        ).fetchone():
            raise HTTPException(409, "This email already has an account.")
        user = {
            "id": str(uuid4()),
            "email": token["email"],
            "name": body.name.strip(),
            "password": password_hash(body.password),
            "org": token["org"],
            "role": token["role"],
        }
        c.execute(
            "INSERT INTO users (id,email,name,password,org,role) VALUES (:id,:email,:name,:password,:org,:role)",
            user,
        )
        session(c, user, response)
        audit(c, user, "member.joined", user["id"])
    return {"ok": True}
