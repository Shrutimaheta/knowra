"""Bounded, curated cloud demo. Never imports the operator's local workspace."""

import hashlib
import io
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from app.rag import chunk_pages
from app.security import password_hash, verify_password
from app.store import db

NOTICE = (
    "Shared fictional-data demo. Do not enter private information. "
    "Keyword search is enabled; uploads, local OCR and account administration are disabled. "
    "Data is stored in Neon; the app can sleep while idle."
)


def enabled():
    return os.getenv("APP_ENV") == "demo"


def permits(method, path):
    if method in ("GET", "HEAD", "OPTIONS"):
        return True
    if method == "POST":
        return bool(re.fullmatch(
            r"/api/v1/(?:auth/(?:login|logout)|search|conversations|"
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
        if c.execute("SELECT id FROM users WHERE id<>? LIMIT 1", (account,)).fetchone():
            raise RuntimeError("Use a new dedicated Neon database for the curated demo")
        current = c.execute("SELECT password FROM users WHERE id=?", (account,)).fetchone()
        if current:
            if not verify_password(password, current["password"]):
                c.execute("UPDATE users SET password=? WHERE id=?", (password_hash(password), account))
                c.execute("DELETE FROM sessions WHERE user_id=?", (account,))
        else:
            c.execute("INSERT INTO organizations VALUES (?,?)", (org, "Knowra public demo"))
            c.execute("INSERT INTO users VALUES (?,?,?,?,?,?)", (account, email, "Demo reviewer", password_hash(password), org, "viewer"))
        directory = Path(__file__).parent / "static/demo"
        sources = [(directory / f"policy-{year}.pdf").read_bytes() for year in (2025, 2026)]
        fixtures = [("Handbook 2025.pdf", [sources[0]]), ("Handbook 2026.pdf", [sources[1]]), ("Workplace policy.pdf", sources)]
        for title, originals in fixtures:
            document = identity(title)
            if c.execute("SELECT id FROM documents WHERE id=?", (document,)).fetchone():
                continue
            c.execute("INSERT INTO documents (id,org,owner,title,category,visibility,status,content,created,version) VALUES (?,?,?,?,?,?,'ready','',?,?)", (document, org, account, title, "People", "workspace", stamp, len(originals)))
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
            _version(c, document, title, 1, output.getvalue(), pages, stamp, "Pre-indexed fictional image sample; live OCR is disabled in this cloud demo.")


def _version(c, document, title, number, original, pages, stamp, warning=None):
    version = identity(title + "/" + str(number))
    layout = [{"method": "curated sample", "tables": [], "warnings": [warning] if warning else []} for _ in pages]
    c.execute("INSERT INTO document_versions (id,document,number,filename,original,checksum,pages,status,created,layout_meta) VALUES (?,?,?,?,?,?,?,'ready',?,?)", (version, document, number, title, original, hashlib.sha256(original).hexdigest(), json.dumps(pages), stamp, json.dumps(layout)))
    for index, (page, content) in enumerate(chunk_pages(pages)):
        c.execute("INSERT INTO chunks (id,document,content,page,version_id) VALUES (?,?,?,?,?)", (identity(version + "/" + str(index)), document, content, page, version))
