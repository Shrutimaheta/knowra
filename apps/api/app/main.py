import hashlib
import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from app.api.v1.routes import router
from app.config import validate_runtime
from app.demo import bootstrap as bootstrap_demo
from app.demo import enabled as demo_enabled
from app.demo import permits as demo_permits
from app.demo import public_dashboard as public_demo_dashboard
from app.embeddings import model_name, warmup
from app.knowledge_map import router as knowledge_map_router
from app.neon_auth import enabled as neon_login
from app.neon_auth import router as neon_auth_router
from app.routes.common import client_ip, uid
from app.security import router as security_router
from app.store import db, initialize
from app.worker import loop
from fastapi import FastAPI, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool


@asynccontextmanager
async def lifespan(app):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    validate_runtime()
    if os.getenv("AUTO_MIGRATE", "true") == "true":
        initialize()
    if demo_enabled() and os.getenv("DEMO_BOOTSTRAP", "true") == "true":
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





@app.middleware("http")
async def protect(request, call_next):
    started = time.monotonic()
    request_id = uid()
    if demo_enabled() and not demo_permits(request.method, request.url.path):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=403, content={"detail": "This workspace has uploads and administration disabled. Use the supplied fictional sources."})
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        allowed_origins = {os.getenv("PUBLIC_URL", str(request.base_url)).rstrip("/")}
        if os.getenv("VERCEL") == "1" and os.getenv("VERCEL_URL"):
            allowed_origins.add("https://" + os.environ["VERCEL_URL"])
        if origin and origin not in allowed_origins:
            return Response("Cross-origin requests are forbidden", status_code=403)
    if request.url.path.startswith("/api/"):
        if (
            request.headers.get("content-length", "0").isdigit()
            and int(request.headers.get("content-length", "0")) > 12 * 1024 * 1024
        ):
            return Response("Request exceeds upload limit", status_code=413)
        host = client_ip(request)
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


@app.get("/")
def home():
    if public_demo_dashboard():
        from fastapi.responses import HTMLResponse

        html = (STATIC / "index.html").read_text(encoding="utf-8")
        html = html.replace('id="auth" class="auth-layout"', 'id="auth" class="auth-layout hidden"')
        html = html.replace('id="demo-loading" class="loading hidden"', 'id="demo-loading" class="loading"')
        return HTMLResponse(html)
    return FileResponse(STATIC / "index.html")



from app.routes import auth, conversations, documents, workspace  # noqa: E402

for module in (auth, documents, conversations, workspace):
    app.include_router(module.router)
