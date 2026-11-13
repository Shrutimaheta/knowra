"""Helpers shared by the route modules."""

import os
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, Field


def uid():
    return str(uuid4())


def now():
    return datetime.now(UTC).isoformat()


def audit(c, user, action, target):
    c.execute(
        "INSERT INTO audit VALUES (?,?,?,?,?,?)",
        (uid(), user["org"], user["id"], action, target, now()),
    )


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=10, max_length=128)


class Registration(Credentials):
    name: str = Field(min_length=1, max_length=100)
    workspace: str = Field(min_length=1, max_length=100)


def permitted_document(c, document_id, user):
    row = c.execute(
        "SELECT * FROM documents WHERE id=? AND org=? AND (visibility='workspace' OR owner=?)",
        (document_id, user["org"], user["id"]),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Document not found.")
    return dict(row)


def client_ip(request):
    """Address used for request limits.

    On Vercel the function sees Vercel's own network address, so every visitor
    would share one limit. Vercel's edge sets x-vercel-forwarded-for and
    overwrites client-supplied forwarding headers, so it is trusted there only.
    Elsewhere, uvicorn's --proxy-headers already resolves request.client.
    """
    if os.getenv("VERCEL") == "1":
        forwarded = request.headers.get("x-vercel-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "local"
