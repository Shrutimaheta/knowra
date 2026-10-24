"""Bounded, curated cloud demo. Never imports the operator's local workspace."""

import hashlib
import io
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from app.demo_catalog import DIRECTORY as BUSINESS_DIRECTORY
from app.demo_catalog import DOCUMENTS as BUSINESS_DOCUMENTS
from app.rag import chunk_pages
from app.security import digest, password_hash, session, verify_password
from app.store import db
from fastapi import HTTPException

NOTICE = (
    "Fictional sample workspace. Your chats and reviews are separate from other visitors. "
    "Do not enter private information. Up to 8 questions per visitor per day; shared daily limits apply. "
    "Uploads and live OCR are disabled. The app can sleep while idle."
)
VISITOR_QUESTIONS = 8
DAILY_QUESTIONS = 60
MAX_VISITORS = 250


def enabled():
    return os.getenv("APP_ENV") == "demo"


def public_dashboard():
    return enabled() and os.getenv("DEMO_PUBLIC_DASHBOARD", "true") == "true"


def enter(request, response):
    if not public_dashboard():
        raise HTTPException(404, "Public workspace entry is unavailable.")
    now = time.time()
    org = identity("workspace")
    with db() as c:
        existing = c.execute(
            "SELECT u.id FROM users u JOIN sessions s ON s.user_id=u.id JOIN demo_visitors g ON g.user_id=u.id WHERE s.token=? AND s.expires>? AND g.expires>? AND u.org=? AND u.role='viewer'",
            (digest(request.cookies.get("knowra_session", "")), now, now, org),
        ).fetchone()
        if existing:
            return {"ok": True}
        # Serialize capacity and cleanup across processes without touching other workspaces.
        if not c.execute("SELECT id FROM organizations WHERE id=?", (org,)).fetchone():
            raise HTTPException(503, "The workspace is still preparing. Try again shortly.")
        c.execute("UPDATE organizations SET name=name WHERE id=?", (org,))
        expired = c.execute(
            "SELECT g.user_id FROM demo_visitors g JOIN users u ON u.id=g.user_id WHERE g.expires<? AND u.org=? AND u.role='viewer' AND u.id<>? LIMIT 25",
            (now, org, identity("reviewer")),
        ).fetchall()
        for row in expired:
            user_id = row["user_id"]
            c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            c.execute("DELETE FROM conversations WHERE user_id=? AND org=?", (user_id, org))
            c.execute("DELETE FROM audit WHERE actor=? AND org=?", (user_id, org))
            c.execute("DELETE FROM users WHERE id=? AND org=? AND role='viewer'", (user_id, org))
        c.execute("DELETE FROM demo_usage WHERE expires<?", (now,))
        if c.execute("SELECT COUNT(*) AS n FROM demo_visitors").fetchone()["n"] >= MAX_VISITORS:
            raise HTTPException(503, "The workspace is busy. Please try again later.")
        user = {"id": str(uuid4()), "org": org}
        c.execute(
            "INSERT INTO users (id,email,name,password,org,role) VALUES (?,?,?,'!visitor-password-disabled',?,'viewer')",
            (user["id"], "visitor-" + user["id"] + "@example.test", "Visitor", org),
        )
        expires = now + 86400
        c.execute("INSERT INTO demo_visitors (user_id,expires) VALUES (?,?)", (user["id"], expires))
        token = session(c, user, response, "Workspace visitor")
        c.execute("UPDATE sessions SET expires=? WHERE token=?", (expires, token))
    return {"ok": True}


def consume_question(user):
    if not enabled():
        return
    now = time.time()
    day, minute = int(now // 86400), int(now // 60)
    limits = [
        ("visitor:" + user["id"], "day:" + str(day), VISITOR_QUESTIONS, (day + 1) * 86400),
        ("visitor:" + user["id"], "minute:" + str(minute), 3, (minute + 1) * 60),
        ("all-visitors", "day:" + str(day), DAILY_QUESTIONS, (day + 1) * 86400),
    ]
    with db() as c:
        for bucket, period, limit, expires in limits:
            row = c.execute(
                "INSERT INTO demo_usage (bucket,period,count,expires) VALUES (?,?,1,?) ON CONFLICT(bucket,period) DO UPDATE SET count=demo_usage.count+1 WHERE demo_usage.count<? RETURNING count",
                (bucket, period, expires, limit),
            ).fetchone()
            if not row:
                wait = max(1, int(expires - now) + 1)
                if period.startswith("minute:"):
                    message = "Please wait a minute before asking another question. You can still explore the documents."
                elif bucket == "all-visitors":
                    message = "The shared question budget is used for today. You can still search and explore the documents."
                else:
                    message = "Your daily question limit has been reached. You can still search and explore the documents."
                raise HTTPException(429, message, headers={"Retry-After": str(wait)})


def permits(method, path):
    if method in ("GET", "HEAD", "OPTIONS"):
        return True
    if method == "POST":
        return bool(re.fullmatch(
            r"/api/v1/(?:auth/(?:demo|login|logout)|search|conversations|"
            r"conversations/[^/]+/(?:messages|stream)|messages/[^/]+/feedback|"
            r"conflicts/(?:scan|review)|documents/[^/]+/versions/[^/]+/evidence)", path
        ))
    return method == "DELETE" and bool(re.fullmatch(r"/api/v1/conversations/[^/]+", path))


def identity(value):
    return str(uuid5(NAMESPACE_URL, "knowra-render-demo-v1/" + value))


def bootstrap():
    """Idempotently index only repository-owned fictional files, without OCR/model loads."""
    import pymupdf
    from PIL import Image, ImageDraw

    stamp = datetime.now(UTC).isoformat()
    email = "demo@knowra.example"
    org, account = identity("workspace"), identity("reviewer")
    password = os.environ["DEMO_PASSWORD"]
    with db() as c:
        if c.execute("SELECT u.id FROM users u WHERE u.id<>? AND NOT EXISTS (SELECT 1 FROM demo_visitors g WHERE g.user_id=u.id AND u.org=? AND u.role='viewer') LIMIT 1", (account, org)).fetchone():
            raise RuntimeError("Use a new dedicated Neon database for the curated demo")
        current = c.execute("SELECT password FROM users WHERE id=?", (account,)).fetchone()
        if current:
            if not verify_password(password, current["password"]):
                c.execute("UPDATE users SET password=? WHERE id=?", (password_hash(password), account))
                c.execute("DELETE FROM sessions WHERE user_id=?", (account,))
        else:
            c.execute("INSERT INTO organizations VALUES (?,?)", (org, "Knowra workspace"))
            c.execute("INSERT INTO users VALUES (?,?,?,?,?,?)", (account, email, "Workspace reviewer", password_hash(password), org, "viewer"))
        c.execute("UPDATE organizations SET name=? WHERE id=? AND name=?", ("Knowra workspace", org, "Knowra public demo"))
        c.execute("UPDATE users SET name=? WHERE org=? AND name=? AND id IN (SELECT user_id FROM demo_visitors)", ("Visitor", org, "Demo visitor"))
        c.execute("UPDATE users SET name=? WHERE id=? AND name=?", ("Workspace reviewer", account, "Demo reviewer"))
        directory = Path(__file__).parent / "static/demo"
        sources = [(directory / f"policy-{year}.pdf").read_bytes() for year in (2025, 2026)]
        fixtures = [("Handbook 2025.pdf", "People", [sources[0]]), ("Handbook 2026.pdf", "People", [sources[1]]), ("Workplace policy.pdf", "People", sources)]
        fixtures += [(title, category, [(BUSINESS_DIRECTORY / name).read_bytes() for name in versions])
                     for title, category, versions in BUSINESS_DOCUMENTS]
        for title, category, originals in fixtures:
            document = identity(title)
            if c.execute("SELECT id FROM documents WHERE id=?", (document,)).fetchone():
                continue
            c.execute("INSERT INTO documents (id,org,owner,title,category,visibility,status,content,created,version) VALUES (?,?,?,?,?,?,'ready','',?,?)", (document, org, account, title, category, "workspace", stamp, len(originals)))
            for number, original in enumerate(originals, 1):
                with pymupdf.open(stream=original, filetype="pdf") as pdf:
                    pages = [page.get_text(sort=True) for page in pdf]
                _version(c, document, title, number, original, pages, stamp)
            c.execute("UPDATE documents SET content=? WHERE id=?", ("\n\n".join(pages), document))
        title = "Fictional expense receipt.png"
        document = identity(title)
        if not c.execute("SELECT id FROM documents WHERE id=?", (document,)).fetchone():
            image = Image.new("RGB", (900, 550), "white")
            draw = ImageDraw.Draw(image)
            lines = ["FICTIONAL DEMO RECEIPT", "Acme Demo Supplies", "Receipt: DEMO-1042", "Office equipment: INR 3500", "Tax: INR 630", "Total: INR 4130", "Date: 2026-10-01"]
            for i, line in enumerate(lines):
                draw.text((45, 35 + i * 65), line, fill="black", font_size=30)
            output = io.BytesIO()
            image.save(output, format="PNG")
            pages = ["\n".join(lines)]
            c.execute("INSERT INTO documents (id,org,owner,title,category,visibility,status,content,created) VALUES (?,?,?,?,?,?,'ready',?,?)", (document, org, account, title, "Finance", "workspace", pages[0], stamp))
            _version(c, document, title, 1, output.getvalue(), pages, stamp, "Pre-indexed fictional image sample; live OCR is disabled in this hosted workspace.")


def _version(c, document, title, number, original, pages, stamp, warning=None):
    version = identity(title + "/" + str(number))
    layout = [{"method": "curated sample", "tables": [], "warnings": [warning] if warning else []} for _ in pages]
    c.execute("INSERT INTO document_versions (id,document,number,filename,original,checksum,pages,status,created,layout_meta) VALUES (?,?,?,?,?,?,?,'ready',?,?)", (version, document, number, title, original, hashlib.sha256(original).hexdigest(), json.dumps(pages), stamp, json.dumps(layout)))
    for index, (page, content) in enumerate(chunk_pages(pages)):
        c.execute("INSERT INTO chunks (id,document,content,page,version_id) VALUES (?,?,?,?,?)", (identity(version + "/" + str(index)), document, content, page, version))
