"""Analytics, audit log, members, demo seeding and readiness."""

import os

from app.demo_catalog import DIRECTORY as BUSINESS_DIRECTORY
from app.demo_catalog import DOCUMENTS as BUSINESS_DOCUMENTS
from app.routes.common import Credentials, audit, now, uid
from app.routes.documents import documents
from app.security import admin, current_user, password_hash
from app.store import db, engine
from app.worker import enqueue, run_once
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import Field

router = APIRouter()


@router.get("/api/v1/analytics")
def analytics(user=Depends(current_user)):
    return analytics_summary(user, documents(user))


def analytics_summary(user, docs):
    with db() as c:
        counts = c.execute(
            "SELECT COUNT(*) AS questions, COALESCE(AVG(m.latency),0) AS latency, COALESCE(SUM(m.tokens),0) AS tokens, SUM(CASE WHEN m.feedback=1 THEN 1 ELSE 0 END) AS positive FROM messages m JOIN conversations c ON c.id=m.conversation WHERE c.org=? AND c.user_id=? AND m.role='assistant'",
            (user["org"], user["id"]),
        ).fetchone()
    return dict(counts) | {
        "documents": len(docs),
        "ready": sum(d["status"] == "ready" for d in docs),
    }


@router.get("/api/v1/audit")
def audit_log(user=Depends(admin)):
    with db() as c:
        return [
            dict(r)
            for r in c.execute(
                "SELECT a.*,u.name FROM audit a JOIN users u ON u.id=a.actor WHERE a.org=? ORDER BY a.created DESC LIMIT 100",
                (user["org"],),
            )
        ]


@router.get("/api/v1/members")
def members(user=Depends(admin)):
    with db() as c:
        return [
            dict(r)
            for r in c.execute(
                "SELECT id,name,email,role FROM users WHERE org=?", (user["org"],)
            )
        ]


class Member(Credentials):
    name: str = Field(min_length=1, max_length=100)
    role: str = "member"


@router.post("/api/v1/members", status_code=201)
def add_member(body: Member, user=Depends(admin)):
    if os.getenv("APP_ENV") == "production":
        raise HTTPException(
            403, "Use the invitation flow so members choose their own passwords."
        )
    if body.role not in ("member", "viewer", "admin") or "@" not in body.email:
        raise HTTPException(422, "Invalid email or role.")
    with db() as c:
        if c.execute(
            "SELECT id FROM users WHERE email=?", (body.email.strip().lower(),)
        ).fetchone():
            raise HTTPException(409, "This email already has an account.")
        member_id = uid()
        c.execute(
            "INSERT INTO users VALUES (?,?,?,?,?,?)",
            (
                member_id,
                body.email.strip().lower(),
                body.name,
                password_hash(body.password),
                user["org"],
                body.role,
            ),
        )
        audit(c, user, "member.created", member_id)
    return {"id": member_id}


@router.post("/api/v1/demo/seed")
def seed(background: BackgroundTasks, user=Depends(admin)):
    samples = [
        (
            "Employee handbook 2026.md",
            "People",
            "FICTIONAL DEMO DATA. The 2026 annual leave allowance is 24 days. Employees joining during the year receive prorated leave. New employees have a 90-day probation period. Remote work is allowed three days each week with manager approval. Unused leave up to five days may carry into the next year.",
        ),
        (
            "Employee handbook 2025.md",
            "People",
            "FICTIONAL DEMO DATA. The 2025 annual leave allowance was 20 days. Employees could work remotely two days per week. Up to three unused leave days could carry into the next year.",
        ),
        (
            "Security and access policy.md",
            "Security",
            "FICTIONAL DEMO DATA. All team members must enable multifactor authentication. Report security incidents to the security team within one hour. Customer data must be encrypted in transit and at rest. Access reviews happen quarterly. Never share passwords or API keys.",
        ),
        (
            "Customer onboarding playbook.md",
            "Operations",
            "FICTIONAL DEMO DATA. Customer onboarding starts with a discovery meeting. The account manager collects requirements within two business days. Implementation takes ten business days. Schedule training before launch and a success review thirty days after launch.",
        ),
    ]
    created = 0
    with db() as c:
        for title, category, content in samples:
            if c.execute(
                "SELECT id FROM documents WHERE org=? AND title=?", (user["org"], title)
            ).fetchone():
                continue
            document_id = uid()
            c.execute(
                "INSERT INTO documents (id,org,owner,title,category,visibility,status,content,created) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    document_id,
                    user["org"],
                    user["id"],
                    title,
                    category,
                    "workspace",
                    "processing",
                    content,
                    now(),
                ),
            )
            version = enqueue(c, document_id, title, content.encode(), [content], 1)
            if os.getenv("EAGER_INGESTION", "false") == "true":
                background.add_task(run_once, version)
            created += 1
        for title, category, filenames in BUSINESS_DOCUMENTS:
            if c.execute(
                "SELECT id FROM documents WHERE org=? AND title=?", (user["org"], title)
            ).fetchone():
                continue
            document_id = uid()
            c.execute(
                "INSERT INTO documents (id,org,owner,title,category,visibility,status,content,created,version) VALUES (?,?,?,?,?,?,'queued','',?,?)",
                (
                    document_id,
                    user["org"],
                    user["id"],
                    title,
                    category,
                    "workspace",
                    now(),
                    len(filenames),
                ),
            )
            for number, filename in enumerate(filenames, 1):
                version = enqueue(
                    c,
                    document_id,
                    filename,
                    (BUSINESS_DIRECTORY / filename).read_bytes(),
                    [],
                    number,
                )
                if os.getenv("EAGER_INGESTION", "false") == "true":
                    background.add_task(run_once, version)
            created += 1
        audit(c, user, "demo.seeded", str(created))
    return {"created": created}


@router.get("/api/v1/health/ready")
def readiness():
    with db() as c:
        revision = c.execute("SELECT version_num FROM alembic_version").fetchone()[
            "version_num"
        ]
        pending = c.execute(
            "SELECT COUNT(*) AS n FROM ingestion_jobs WHERE status IN ('queued','running')"
        ).fetchone()["n"]
        failed = c.execute(
            "SELECT COUNT(*) AS n FROM ingestion_jobs WHERE status='failed'"
        ).fetchone()["n"]
    return {
        "status": "ok",
        "database": engine().dialect.name,
        "revision": revision,
        "pending_jobs": pending,
        "failed_jobs": failed,
    }
