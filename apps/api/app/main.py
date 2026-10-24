import hashlib
import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.api.v1.routes import router
from app.config import validate_runtime
from app.conflict_routes import register_conflict_routes
from app.demo import NOTICE as DEMO_NOTICE
from app.demo import bootstrap as bootstrap_demo
from app.demo import consume_question as consume_demo_question
from app.demo import enabled as demo_enabled
from app.demo import enter as enter_demo
from app.demo import permits as demo_permits
from app.demo import public_dashboard as public_demo_dashboard
from app.demo_catalog import DIRECTORY as BUSINESS_DIRECTORY
from app.demo_catalog import DOCUMENTS as BUSINESS_DOCUMENTS
from app.embeddings import model_name, query_vector, warmup
from app.extraction import visual_file
from app.knowledge_map import router as knowledge_map_router
from app.malware import scan
from app.neon_auth import enabled as neon_login
from app.neon_auth import router as neon_auth_router
from app.object_storage import original as stored_original
from app.processing import validate
from app.providers import generation_provider
from app.rag import retrieve, single_topic_query, stream_answer, tokens
from app.security import admin, current_user, password_hash, session, verify_password
from app.security import router as security_router
from app.store import db, engine, initialize
from app.worker import enqueue, loop, run_once
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool


@asynccontextmanager
async def lifespan(app):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    validate_runtime()
    if os.getenv("AUTO_MIGRATE", "true") == "true":
        initialize()
    if demo_enabled():
        bootstrap_demo()
    stop = threading.Event()
    worker = None
    if model_name() and os.getenv("WARM_EMBEDDINGS", "true") == "true":
        threading.Thread(
            target=warmup, daemon=True, name="knowra-search-warmup"
        ).start()
    if os.getenv("EMBEDDED_WORKER", "true") == "true":
        worker = threading.Thread(
            target=loop, args=(stop,), daemon=True, name="knowra-ingestion"
        )
        worker.start()
    try:
        yield
    finally:
        stop.set()
        if worker:
            await run_in_threadpool(worker.join, 5)


app = FastAPI(
    title="Knowra AI API",
    version="2.0.0",
    lifespan=lifespan,
    docs_url=None if os.getenv("APP_ENV") in ("production", "demo") else "/docs",
    redoc_url=None,
    openapi_url=None if os.getenv("APP_ENV") in ("production", "demo") else "/openapi.json",
)


@app.exception_handler(IntegrityError)
async def conflict_handler(request, error):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=409,
        content={
            "detail": "This record was changed by another request or already exists. Please refresh and retry."
        },
    )


app.include_router(security_router)
app.include_router(neon_auth_router)
app.include_router(knowledge_map_router)
app.include_router(router, prefix="/api/v1")
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def uid():
    return str(uuid4())


def now():
    return datetime.now(UTC).isoformat()


def audit(c, user, action, target):
    c.execute(
        "INSERT INTO audit VALUES (?,?,?,?,?,?)",
        (uid(), user["org"], user["id"], action, target, now()),
    )


@app.middleware("http")
async def protect(request, call_next):
    started = time.monotonic()
    request_id = uid()
    if demo_enabled() and not demo_permits(request.method, request.url.path):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=403, content={"detail": "This workspace has uploads and administration disabled. Use the supplied fictional sources."})
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and origin != os.getenv("PUBLIC_URL", str(request.base_url)).rstrip(
            "/"
        ):
            return Response("Cross-origin requests are forbidden", status_code=403)
    if request.url.path.startswith("/api/"):
        if (
            request.headers.get("content-length", "0").isdigit()
            and int(request.headers.get("content-length", "0")) > 12 * 1024 * 1024
        ):
            return Response("Request exceeds upload limit", status_code=413)
        host = request.client.host if request.client else "local"
        auth = request.url.path.startswith(
            "/api/v1/auth"
        ) or request.url.path.startswith("/api/v1/invitations/accept")
        bucket = hashlib.sha256(
            (host + (":auth" if auth else ":api")).encode()
        ).hexdigest()
        window = int(time.time() // 60)
        count = await run_in_threadpool(request_count, bucket, window)
        if count > (20 if auth else 180):
            return Response(
                "Too many requests. Retry in a minute.",
                status_code=429,
                headers={"Retry-After": "60"},
            )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Request-ID"] = request_id
    logging.getLogger("knowra.requests").info(
        json.dumps(
            {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000),
            }
        )
    )
    if os.getenv("APP_ENV") in ("production", "demo"):
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
    )
    if neon_login():
        from urllib.parse import urlsplit

        auth_url = urlsplit(os.getenv("NEON_AUTH_BASE_URL", ""))
        if auth_url.scheme == "https" and auth_url.hostname:
            auth_origin = "https://" + auth_url.netloc
            response.headers["Content-Security-Policy"] += f"; connect-src 'self' {auth_origin}; frame-src {auth_origin}"
    if request.url.path == "/docs":
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; frame-ancestors 'none'"
        )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def request_count(bucket, window):
    """Keep database I/O and lock waits off the async server event loop."""
    with db() as c:
        count = c.execute(
            'INSERT INTO request_limits (bucket,"window",count) VALUES (?,?,1) ON CONFLICT (bucket,"window") DO UPDATE SET count=request_limits.count+1 RETURNING count',
            (bucket, window),
        ).fetchone()["count"]
        if count == 1:
            c.execute('DELETE FROM request_limits WHERE "window"<?', (window - 2,))
    return count


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=10, max_length=128)


class Registration(Credentials):
    name: str = Field(min_length=1, max_length=100)
    workspace: str = Field(min_length=1, max_length=100)


@app.get("/")
def home():
    if public_demo_dashboard():
        from fastapi.responses import HTMLResponse

        html = (STATIC / "index.html").read_text(encoding="utf-8")
        html = html.replace('id="auth" class="auth-layout"', 'id="auth" class="auth-layout hidden"')
        html = html.replace('id="demo-loading" class="loading hidden"', 'id="demo-loading" class="loading"')
        return HTMLResponse(html)
    return FileResponse(STATIC / "index.html")


@app.get("/api/v1/app-config")
def app_config():
    return {"demo": demo_enabled(), "public_dashboard": public_demo_dashboard(), "notice": DEMO_NOTICE if demo_enabled() else "", "login_email": "demo@knowra.example" if demo_enabled() else "", "auth_provider": "neon" if neon_login() else "local", "auth_url": os.getenv("NEON_AUTH_BASE_URL") if neon_login() else None}


@app.post("/api/v1/auth/demo")
def demo_entry(request: Request, response: Response):
    return enter_demo(request, response)


@app.post("/api/v1/auth/register", status_code=201)
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


@app.post("/api/v1/auth/login")
def login(body: Credentials, response: Response, request: Request):
    if neon_login():
        raise HTTPException(409, "Use the managed Neon sign-in form.")
    with db() as c:
        row = c.execute(
            "SELECT * FROM users WHERE email=?", (body.email.strip().lower(),)
        ).fetchone()
        stored = row["password"] if row else password_hash("dummy password")
        valid = verify_password(body.password, stored)
        if not row or not valid:
            raise HTTPException(401, "Email or password is incorrect.")
        if not stored.startswith("$argon2"):
            c.execute(
                "UPDATE users SET password=? WHERE id=?",
                (password_hash(body.password), row["id"]),
            )
        session(c, row, response, request.headers.get("user-agent", "Browser"))
    return {"ok": True}


@app.post("/api/v1/auth/logout")
def logout(request: Request, response: Response, user=Depends(current_user)):
    with db() as c:
        c.execute(
            "DELETE FROM sessions WHERE token=?",
            (hashlib.sha256(request.cookies["knowra_session"].encode()).hexdigest(),),
        )
    response.delete_cookie("knowra_session")
    return {"ok": True}


@app.get("/api/v1/users/me")
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


def permitted_document(c, document_id, user):
    row = c.execute(
        "SELECT * FROM documents WHERE id=? AND org=? AND (visibility='workspace' OR owner=?)",
        (document_id, user["org"], user["id"]),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Document not found.")
    return dict(row)


register_conflict_routes(app, permitted_document, audit)


@app.get("/api/v1/documents/{document_id}/versions/{version_id}/integrity")
def integrity(document_id: str, version_id: str, user=Depends(current_user)):
    from app.neon_functions import source_integrity

    with db() as c:
        permitted_document(c, document_id, user)
        if not c.execute("SELECT id FROM document_versions WHERE id=? AND document=?", (version_id, document_id)).fetchone():
            raise HTTPException(404, "Source version not found.")
    return source_integrity(document_id, version_id, user)


def check_upload(file):
    data = file.file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Files must be 10 MB or smaller.")
    title = (file.filename or "document").replace("\\", "/").split("/")[-1][:200]
    scan(data)
    return data, title, validate(title, data)


def upload_quota(c, user, size):
    # Serialize workspace writes across API instances for atomic quota enforcement.
    c.execute("UPDATE organizations SET name=name WHERE id=?", (user["org"],))
    total = c.execute(
        "SELECT COALESCE(SUM(COALESCE(v.original_size,length(v.original))),0) AS total FROM document_versions v JOIN documents d ON d.id=v.document WHERE d.org=?",
        (user["org"],),
    ).fetchone()["total"]
    if total + size > int(os.getenv("WORKSPACE_STORAGE_MB", "100")) * 1024 * 1024:
        raise HTTPException(
            413,
            "Workspace storage quota reached. Remove unused documents or contact your administrator.",
        )


@app.post("/api/v1/documents", status_code=201)
def upload(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    category: str = Form("General"),
    visibility: str = Form("workspace"),
    user=Depends(current_user),
):
    if user["role"] == "viewer":
        raise HTTPException(403, "Viewers cannot upload documents.")
    if visibility not in ("workspace", "private") or len(category) > 60:
        raise HTTPException(422, "Invalid document settings.")
    data, title, pages = check_upload(file)
    document_id = uid()
    with db() as c:
        upload_quota(c, user, len(data))
        count = c.execute(
            "SELECT COUNT(*) AS n FROM documents WHERE org=?", (user["org"],)
        ).fetchone()["n"]
        if count >= int(os.getenv("WORKSPACE_DOCUMENT_LIMIT", "500")):
            raise HTTPException(413, "Workspace document quota reached.")
        c.execute(
            "INSERT INTO documents (id,org,owner,title,category,visibility,status,content,created) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                document_id,
                user["org"],
                user["id"],
                title,
                category,
                visibility,
                "processing",
                "",
                now(),
            ),
        )
        version = enqueue(c, document_id, title, data, pages, 1)
        audit(c, user, "document.uploaded", document_id)
    if os.getenv("EAGER_INGESTION", "false") == "true":
        background.add_task(run_once, version)
    return {"id": document_id, "version_id": version, "status": "processing"}


@app.post("/api/v1/documents/{document_id}/versions", status_code=201)
def upload_version(
    document_id: str,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    user=Depends(current_user),
):
    data, title, pages = check_upload(file)
    with db() as c:
        upload_quota(c, user, len(data))
        doc = permitted_document(c, document_id, user)
        if user["role"] == "viewer" or (
            doc["owner"] != user["id"] and user["role"] not in ("owner", "admin")
        ):
            raise HTTPException(
                403, "Only the document owner or an administrator can add versions."
            )
        number = doc["version"] + 1
        c.execute(
            "UPDATE documents SET version=?,status='processing',error=NULL WHERE id=?",
            (number, document_id),
        )
        version = enqueue(c, document_id, title, data, pages, number)
        audit(c, user, "document.version_uploaded", document_id)
    if os.getenv("EAGER_INGESTION", "false") == "true":
        background.add_task(run_once, version)
    return {
        "id": document_id,
        "version_id": version,
        "version": number,
        "status": "processing",
    }


@app.get("/api/v1/documents/{document_id}/versions")
def versions(document_id: str, user=Depends(current_user)):
    with db() as c:
        permitted_document(c, document_id, user)
        return [
            dict(r)
            for r in c.execute(
                "SELECT id,number,filename,checksum,status,created FROM document_versions WHERE document=? ORDER BY number DESC",
                (document_id,),
            )
        ]


@app.get("/api/v1/documents/{document_id}/versions/{version_id}")
def version_detail(document_id: str, version_id: str, user=Depends(current_user)):
    with db() as c:
        permitted_document(c, document_id, user)
        version = c.execute(
            "SELECT id,number,filename,pages,layout_meta,status,checksum FROM document_versions WHERE id=? AND document=?",
            (version_id, document_id),
        ).fetchone()
        if not version:
            raise HTTPException(404, "Source version not found.")
        return dict(version) | {
            "pages": json.loads(version["pages"]),
            "layout_meta": json.loads(version["layout_meta"]),
        }


@app.get("/api/v1/documents/{document_id}/versions/{version_id}/pages/{number}/image")
def source_image(
    document_id: str, version_id: str, number: int, user=Depends(current_user)
):
    from app.extraction import ExtractionError
    from app.processing import page_image

    with db() as c:
        permitted_document(c, document_id, user)
        version = c.execute(
            "SELECT original,original_key,filename FROM document_versions WHERE id=? AND document=?",
            (version_id, document_id),
        ).fetchone()
        if (
            not version
            or (version["original"] is None and not version["original_key"])
            or not visual_file(version["filename"])
        ):
            raise HTTPException(404, "PDF or image source not found.")
        source = dict(version)
    data = stored_original(source)
    try:
        image = page_image(data, number)
    except ExtractionError as error:
        raise HTTPException(404, str(error)) from None
    return Response(
        image, media_type="image/png", headers={"Cache-Control": "no-store"}
    )


@app.get("/api/v1/documents/{document_id}/compare")
def compare_versions(
    document_id: str, from_version: str, to_version: str, user=Depends(current_user)
):
    from app.comparison import compare_pages

    if from_version == to_version:
        raise HTTPException(422, "Choose two different versions.")
    with db() as c:
        document = permitted_document(c, document_id, user)
        selected = []
        for version_id in (from_version, to_version):
            version = c.execute(
                "SELECT id,number,filename,pages,status FROM document_versions WHERE id=? AND document=?",
                (version_id, document_id),
            ).fetchone()
            if not version:
                raise HTTPException(404, "Source version not found.")
            if version["status"] != "ready":
                raise HTTPException(
                    409, "Both versions must finish indexing before comparison."
                )
            selected.append(dict(version))
    if not any(p.strip() for p in json.loads(selected[0]["pages"])) or not any(
        p.strip() for p in json.loads(selected[1]["pages"])
    ):
        raise HTTPException(
            422,
            "Both versions need extracted text to compare. Use visual analysis for images without readable text.",
        )
    result = compare_pages(*[json.loads(v["pages"]) for v in selected])
    return result | {
        "document": document_id,
        "title": document["title"],
        "before": {k: v for k, v in selected[0].items() if k != "pages"},
        "after": {k: v for k, v in selected[1].items() if k != "pages"},
    }


class EvidenceRequest(BaseModel):
    page: int = Field(ge=1, le=300)
    text: str = Field(min_length=1, max_length=4000)


@app.post("/api/v1/documents/{document_id}/versions/{version_id}/evidence")
def source_evidence(
    document_id: str, version_id: str, body: EvidenceRequest, user=Depends(current_user)
):
    from app.processing import highlight

    with db() as c:
        permitted_document(c, document_id, user)
        version = c.execute(
            "SELECT pages,original,original_key,filename,status FROM document_versions WHERE id=? AND document=?",
            (version_id, document_id),
        ).fetchone()
        if not version:
            raise HTTPException(404, "Source version not found.")
        if version["status"] != "ready":
            raise HTTPException(409, "Wait for this version to finish indexing.")
        pages = json.loads(version["pages"])
        if body.page > len(pages):
            raise HTTPException(404, "Source page not found.")
        if len(pages[body.page - 1]) > 100_000:
            raise HTTPException(
                413,
                "This page is too large to highlight. Open the original source instead.",
            )
        source = dict(version)
    data = stored_original(source) if visual_file(source["filename"]) else None
    return highlight(pages, body.page, body.text, data)


@app.get("/api/v1/documents/{document_id}/versions/{version_id}/original")
def original(document_id: str, version_id: str, user=Depends(current_user)):
    from urllib.parse import quote

    with db() as c:
        permitted_document(c, document_id, user)
        version = c.execute(
            "SELECT original,original_key,filename,pages FROM document_versions WHERE id=? AND document=?",
            (version_id, document_id),
        ).fetchone()
        if not version:
            raise HTTPException(404, "Source version not found.")
        data = stored_original(dict(version))
        filename = version["filename"]
        if data is None:
            data = "\n\n".join(json.loads(version["pages"])).encode()
            filename += ".legacy-extract.txt"
        media = (
            "application/pdf"
            if filename.lower().endswith(".pdf")
            else {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
            }.get(Path(filename).suffix.lower(), "text/plain; charset=utf-8")
        )
        return Response(
            bytes(data),
            media_type=media,
            headers={
                "Content-Disposition": "inline; filename*=UTF-8''"
                + quote(filename, safe=""),
                "Cache-Control": "no-store",
            },
        )


@app.post("/api/v1/documents/{document_id}/retry")
def retry_document(document_id: str, user=Depends(current_user)):
    with db() as c:
        doc = permitted_document(c, document_id, user)
        if user["role"] == "viewer" or (
            doc["owner"] != user["id"] and user["role"] not in ("owner", "admin")
        ):
            raise HTTPException(
                403, "Only the owner or an administrator can retry indexing."
            )
        job = c.execute(
            "SELECT j.* FROM ingestion_jobs j JOIN document_versions v ON v.id=j.version_id WHERE v.document=? AND v.number=?",
            (document_id, doc["version"]),
        ).fetchone()
        if not job or job["status"] != "failed":
            raise HTTPException(409, "Only failed jobs can be retried.")
        c.execute(
            "UPDATE ingestion_jobs SET status='queued',attempts=0,available=?,lease_until=NULL,lease_token=NULL,error=NULL WHERE id=?",
            (time.time(), job["id"]),
        )
        c.execute(
            "UPDATE documents SET status='processing',error=NULL WHERE id=?",
            (document_id,),
        )
        c.execute(
            "UPDATE document_versions SET status='queued' WHERE id=?",
            (job["version_id"],),
        )
        audit(c, user, "document.retry", document_id)
    return {"ok": True}


@app.get("/api/v1/documents")
def documents(user=Depends(current_user)):
    with db() as c:
        return [
            dict(r)
            for r in c.execute(
                "SELECT id,title,category,visibility,status,error,created,version FROM documents WHERE org=? AND (visibility='workspace' OR owner=?) ORDER BY created DESC",
                (user["org"], user["id"]),
            )
        ]


@app.get("/api/v1/documents/{document_id}")
def document(document_id: str, user=Depends(current_user)):
    with db() as c:
        return permitted_document(c, document_id, user)


@app.delete("/api/v1/documents/{document_id}")
def delete_document(document_id: str, user=Depends(current_user)):
    with db() as c:
        doc = permitted_document(c, document_id, user)
        if doc["owner"] != user["id"] and user["role"] not in ("owner", "admin"):
            raise HTTPException(
                403, "Only the owner or an administrator can delete this document."
            )
        c.execute("DELETE FROM documents WHERE id=?", (document_id,))
        audit(c, user, "document.deleted", document_id)
    return {"ok": True}


class Question(BaseModel):
    content: str = Field(min_length=1, max_length=3000)
    visual_document_id: str | None = Field(default=None, max_length=100)
    visual_page: int | None = Field(default=None, ge=1, le=300)


@app.post("/api/v1/search")
def search(body: Question, user=Depends(current_user)):
    query = body.content.strip()
    if not query:
        raise HTTPException(422, "Enter a search phrase.")
    with db() as c:
        pending = c.execute(
            "SELECT COUNT(*) AS n FROM documents WHERE org=? AND status='processing' AND (visibility='workspace' OR owner=?)",
            (user["org"], user["id"]),
        ).fetchone()["n"]
        if pending:
            raise HTTPException(
                409,
                f"{pending} document(s) are still being indexed. Wait for Ready in the Knowledge library, then ask again.",
            )
        permitted = " FROM chunks ch JOIN documents d ON d.id=ch.document JOIN document_versions v ON v.id=ch.version_id WHERE d.org=? AND v.number=d.version AND v.status='ready' AND (d.visibility='workspace' OR d.owner=?)"
        select = "SELECT ch.id,ch.document,ch.content,ch.page,ch.version_id,ch.embedding,ch.embedding_model,d.title,v.number AS version"
        if engine().dialect.name == "postgresql":
            # Database-side keyword/vector candidates share the exact permission filter.
            keyword_query = " | ".join("'" + term.replace("'", "''") + "'" for term in list(dict.fromkeys(tokens(query)))[:64])
            rows = [
                dict(r)
                for r in c.execute(
                    select
                    + permitted
                    + " AND to_tsvector('english',ch.content) @@ to_tsquery('english',?) ORDER BY ts_rank_cd(to_tsvector('english',ch.content),to_tsquery('english',?)) DESC LIMIT 200",
                    (user["org"], user["id"], keyword_query, keyword_query),
                )
            ]
            semantic = []
            if model_name() and not (rows and single_topic_query(query)):
                vector = json.dumps(query_vector(query))
                semantic_rows = c.execute(
                    select
                    + ",1-(ch.vector_embedding <=> CAST(? AS vector)) AS similarity"
                    + permitted
                    + " AND ch.embedding_model=? AND ch.vector_embedding IS NOT NULL ORDER BY ch.vector_embedding <=> CAST(? AS vector) LIMIT 30",
                    (vector, user["org"], user["id"], model_name(), vector),
                ).fetchall()
                semantic = [
                    (r["similarity"], dict(r))
                    for r in semantic_rows
                    if r["similarity"] >= float(os.getenv("SEMANTIC_MIN_SCORE", ".30"))
                ]
                seen = {r["id"] for r in rows}
                rows += [row for _, row in semantic if row["id"] not in seen]
            return retrieve(rows, query, semantic=semantic)
        rows = c.execute(select + permitted, (user["org"], user["id"])).fetchall()
    return retrieve(rows, query)


@app.get("/api/v1/conversations")
def conversations(user=Depends(current_user)):
    with db() as c:
        return [
            dict(r)
            for r in c.execute(
                "SELECT * FROM conversations WHERE org=? AND user_id=? ORDER BY created DESC",
                (user["org"], user["id"]),
            )
        ]


@app.post("/api/v1/conversations", status_code=201)
def create_conversation(user=Depends(current_user)):
    conversation_id = uid()
    with db() as c:
        if demo_enabled() and c.execute("SELECT COUNT(*) AS n FROM conversations WHERE user_id=?", (user["id"],)).fetchone()["n"] >= 30:
            raise HTTPException(429, "This workspace allows 30 conversations. Delete an old conversation to continue.")
        c.execute(
            "INSERT INTO conversations VALUES (?,?,?,?,?)",
            (conversation_id, user["org"], user["id"], "New conversation", now()),
        )
    return {"id": conversation_id}


def check_conversation(c, conversation_id, user):
    if not c.execute(
        "SELECT id FROM conversations WHERE id=? AND org=? AND user_id=?",
        (conversation_id, user["org"], user["id"]),
    ).fetchone():
        raise HTTPException(404, "Conversation not found.")


@app.get("/api/v1/conversations/{conversation_id}/messages")
def messages(conversation_id: str, user=Depends(current_user)):
    with db() as c:
        check_conversation(c, conversation_id, user)
        visible = {
            row["id"] for row in c.execute(
                "SELECT id FROM documents WHERE org=? AND (visibility='workspace' OR owner=?)",
                (user["org"], user["id"]),
            )
        }
        result = []
        for r in c.execute(
            "SELECT * FROM messages WHERE conversation=? ORDER BY created",
            (conversation_id,),
        ):
            message = dict(r)
            sources = []
            for index, source in enumerate(json.loads(message["citations"]), 1):
                source.setdefault("citation_number", index)
                if source.get("document") in visible:
                    sources.append(source)
            message["citations"] = sources
            result.append(message)
        return result


def generate_reply(conversation_id, body, user):
    query = body.content.strip()
    if not query:
        raise HTTPException(422, "Enter a question.")
    started = time.monotonic()
    run_token = uid()
    with db() as c:
        check_conversation(c, conversation_id, user)
        if demo_enabled() and c.execute("SELECT COUNT(*) AS n FROM messages m JOIN conversations c ON c.id=m.conversation WHERE c.user_id=?", (user["id"],)).fetchone()["n"] >= 300:
            raise HTTPException(429, "Message limit reached. Delete an old conversation to continue.")
        c.execute("DELETE FROM chat_runs WHERE expires<?", (time.time(),))
        try:
            c.execute(
                "INSERT INTO chat_runs VALUES (?,?,?)",
                (conversation_id, run_token, time.time() + 180),
            )
        except IntegrityError:
            raise HTTPException(
                409, "An answer is already being generated in this conversation."
            ) from None
        history = [
            dict(r)
            for r in c.execute(
                "SELECT role,content FROM messages WHERE conversation=? ORDER BY created DESC LIMIT 6",
                (conversation_id,),
            )
        ][::-1]
    try:
        retrieval_query = query
        import re

        if (
            len(query.split()) < 16
            and history
            and re.search(
                r"\b(it|its|they|their|them|that|those|this|these|more|same|above)\b",
                query,
                re.I,
            )
        ):
            retrieval_query += (
                " "
                + next(
                    (h["content"] for h in reversed(history) if h["role"] == "user"), ""
                )[-1500:]
            )
        page_images = []
        if body.visual_document_id:
            if not body.visual_page:
                raise HTTPException(422, "Choose a page for visual analysis.")
            if not generation_provider():
                raise HTTPException(
                    422, "Visual analysis needs a configured Gemini or OpenAI model."
                )
            import base64

            from app.extraction import ExtractionError
            from app.processing import page_image

            with db() as c:
                doc = permitted_document(c, body.visual_document_id, user)
                version = c.execute(
                    "SELECT * FROM document_versions WHERE document=? AND number=?",
                    (doc["id"], doc["version"]),
                ).fetchone()
                if not version or version["status"] != "ready":
                    raise HTTPException(
                        409, "Wait for this document to finish indexing."
                    )
                if (version["original"] is None and not version["original_key"]) or not visual_file(version["filename"]):
                    raise HTTPException(
                        422, "Visual analysis requires an original PDF or image."
                    )
                pages = json.loads(version["pages"])
                if body.visual_page > len(pages):
                    raise HTTPException(422, "Page number is outside this PDF.")
                source = {
                    "document": doc["id"],
                    "title": doc["title"],
                    "version_id": version["id"],
                    "version": version["number"],
                    "page": body.visual_page,
                    "content": pages[body.visual_page - 1]
                    or "Visual source page; consult the attached image.",
                }
                original_source = dict(version)
            original_data = stored_original(original_source)
            try:
                image = page_image(original_data, body.visual_page)
            except ExtractionError as error:
                raise HTTPException(422, str(error)) from None
            page_images = [
                "data:image/png;base64," + base64.b64encode(image).decode("ascii")
            ]
            sources = [source]
        else:
            sources = search(Question(content=retrieval_query[:3000]), user)
        sources = [
            dict(source, citation_number=i) for i, source in enumerate(sources, 1)
        ]
        consume_demo_question(user)
        yield {"type": "citations", "citations": sources}
        text, mode, total = "", "extractive", 0
        try:
            events = (
                stream_answer(query, sources, history, page_images)
                if page_images
                else stream_answer(query, sources, history)
            )
            for event in events:
                if event["type"] == "delta":
                    text += event["text"]
                    yield event
                elif event["type"] == "usage":
                    mode, total = event["model"], event["tokens"]
        except HTTPException as error:
            if error.status_code != 503 or text or not sources:
                raise
            # Outages must never be misreported as missing evidence. This is
            # an explicit excerpt response, not another provider or a fake LLM.
            text = (
                "AI synthesis is temporarily unavailable. Your document was found.\n"
                "The following are source excerpts, not an AI-generated answer.\n\n"
                + (
                    "The selected page image could not be interpreted. Diagram relationships are not verified.\n\n"
                    if page_images
                    else ""
                )
                + "\n\n".join(
                    f"[{i}] {source['content']}"
                    for i, source in enumerate(sources[:2], 1)
                )
            )
            mode, total = "extractive", 0
            yield {"type": "delta", "text": text}
        if not text:
            raise HTTPException(
                502, "The answer provider returned no content. Please retry."
            )
        # Reject invented citation indices before saving a completed answer.
        import re

        bad = [
            int(n)
            for n in re.findall(r"\[(\d+)\]", text)
            if not 1 <= int(n) <= len(sources)
        ]
        if mode != "extractive" and bad:
            raise HTTPException(
                502, "The model returned invalid source references. Please retry."
            )
        message_id = uid()
        with db() as c:
            check_conversation(c, conversation_id, user)
            if not c.execute(
                "SELECT token FROM chat_runs WHERE conversation=? AND token=? AND expires>?",
                (conversation_id, run_token, time.time()),
            ).fetchone():
                raise HTTPException(409, "This answer expired. Please retry.")
            c.execute(
                "INSERT INTO messages (id,conversation,role,content,created) VALUES (?,?,?,?,?)",
                (uid(), conversation_id, "user", query, now()),
            )
            c.execute(
                "INSERT INTO messages (id,conversation,role,content,citations,created,latency,model,tokens) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    message_id,
                    conversation_id,
                    "assistant",
                    text,
                    json.dumps(sources),
                    now(),
                    int((time.monotonic() - started) * 1000),
                    mode,
                    total,
                ),
            )
            c.execute(
                "UPDATE conversations SET title=? WHERE id=? AND title='New conversation'",
                (query[:70], conversation_id),
            )
            audit(c, user, "chat.answered", conversation_id)
        yield {
            "type": "done",
            "id": message_id,
            "content": text,
            "citations": sources,
            "mode": mode,
            "tokens": total,
        }
    finally:
        with db() as c:
            c.execute(
                "DELETE FROM chat_runs WHERE conversation=? AND token=?",
                (conversation_id, run_token),
            )


@app.post("/api/v1/conversations/{conversation_id}/messages")
def ask(conversation_id: str, body: Question, user=Depends(current_user)):
    result = None
    for event in generate_reply(conversation_id, body, user):
        if event["type"] == "done":
            result = {k: v for k, v in event.items() if k != "type"}
    return result


@app.post("/api/v1/conversations/{conversation_id}/stream")
async def stream_reply(
    conversation_id: str, body: Question, request: Request, user=Depends(current_user)
):
    with db() as c:
        check_conversation(c, conversation_id, user)
    if not body.content.strip():
        raise HTTPException(422, "Enter a question.")
    iterator = generate_reply(conversation_id, body, user)

    async def events():
        try:
            while not await request.is_disconnected():
                item = await run_in_threadpool(lambda: next(iterator, None))
                if item is None:
                    break
                yield "data: " + json.dumps(item) + "\n\n"
        except HTTPException as error:
            yield (
                "data: "
                + json.dumps({"type": "error", "message": error.detail})
                + "\n\n"
            )
        except Exception:
            logging.getLogger("knowra").exception("Answer stream failed")
            yield (
                "data: "
                + json.dumps(
                    {
                        "type": "error",
                        "message": "The answer was interrupted. Please retry.",
                    }
                )
                + "\n\n"
            )
        finally:
            # Shield cleanup so cancellation releases the per-conversation lease.
            import anyio

            with anyio.CancelScope(shield=True):
                await run_in_threadpool(iterator.close)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.delete("/api/v1/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, user=Depends(current_user)):
    with db() as c:
        check_conversation(c, conversation_id, user)
        c.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
    return {"ok": True}


class Feedback(BaseModel):
    value: int = Field(ge=-1, le=1)


@app.post("/api/v1/messages/{message_id}/feedback")
def feedback(message_id: str, body: Feedback, user=Depends(current_user)):
    with db() as c:
        row = c.execute(
            "SELECT conversation FROM messages WHERE id=? AND role=?",
            (message_id, "assistant"),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Message not found.")
        check_conversation(c, row["conversation"], user)
        c.execute("UPDATE messages SET feedback=? WHERE id=?", (body.value, message_id))
    return {"ok": True}


@app.get("/api/v1/analytics")
def analytics(user=Depends(current_user)):
    docs = documents(user)
    with db() as c:
        counts = c.execute(
            "SELECT COUNT(*) AS questions, COALESCE(AVG(m.latency),0) AS latency, COALESCE(SUM(m.tokens),0) AS tokens, SUM(CASE WHEN m.feedback=1 THEN 1 ELSE 0 END) AS positive FROM messages m JOIN conversations c ON c.id=m.conversation WHERE c.org=? AND c.user_id=? AND m.role='assistant'",
            (user["org"], user["id"]),
        ).fetchone()
    return dict(counts) | {
        "documents": len(docs),
        "ready": sum(d["status"] == "ready" for d in docs),
    }


@app.get("/api/v1/audit")
def audit_log(user=Depends(admin)):
    with db() as c:
        return [
            dict(r)
            for r in c.execute(
                "SELECT a.*,u.name FROM audit a JOIN users u ON u.id=a.actor WHERE a.org=? ORDER BY a.created DESC LIMIT 100",
                (user["org"],),
            )
        ]


@app.get("/api/v1/members")
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


@app.post("/api/v1/members", status_code=201)
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


@app.post("/api/v1/demo/seed")
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
            if c.execute("SELECT id FROM documents WHERE org=? AND title=?", (user["org"], title)).fetchone():
                continue
            document_id = uid()
            c.execute(
                "INSERT INTO documents (id,org,owner,title,category,visibility,status,content,created,version) VALUES (?,?,?,?,?,?,'queued','',?,?)",
                (document_id, user["org"], user["id"], title, category, "workspace", now(), len(filenames)),
            )
            for number, filename in enumerate(filenames, 1):
                version = enqueue(c, document_id, filename, (BUSINESS_DIRECTORY / filename).read_bytes(), [], number)
                if os.getenv("EAGER_INGESTION", "false") == "true":
                    background.add_task(run_once, version)
            created += 1
        audit(c, user, "demo.seeded", str(created))
    return {"created": created}


@app.get("/api/v1/health/ready")
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


@app.post("/api/v1/documents/{document_id}/reindex")
def reindex(document_id: str, user=Depends(admin)):
    with db() as c:
        doc = permitted_document(c, document_id, user)
        version = c.execute(
            "SELECT id FROM document_versions WHERE document=? AND number=?",
            (document_id, doc["version"]),
        ).fetchone()
        if not version:
            raise HTTPException(404, "Source version not found.")
        job = c.execute(
            "SELECT id,status FROM ingestion_jobs WHERE version_id=?", (version["id"],)
        ).fetchone()
        if job and job["status"] in ("queued", "running"):
            raise HTTPException(409, "This document is already queued or processing.")
        if job:
            c.execute(
                "UPDATE ingestion_jobs SET status='queued',attempts=0,available=?,lease_until=NULL,lease_token=NULL,error=NULL WHERE id=?",
                (time.time(), job["id"]),
            )
        else:
            c.execute(
                "INSERT INTO ingestion_jobs (id,version_id,status,attempts,available) VALUES (?,?,'queued',0,?)",
                (uid(), version["id"], time.time()),
            )
        c.execute(
            "UPDATE documents SET status='processing',error=NULL WHERE id=?",
            (document_id,),
        )
        c.execute(
            "UPDATE document_versions SET status='queued' WHERE id=?", (version["id"],)
        )
        audit(c, user, "document.reindex", document_id)
    return {"ok": True}
