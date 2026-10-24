"""Live integration proof using only generated fictional data and reserved test identity."""

import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))


def main():
    from check_ai import load_local_settings

    load_local_settings()
    from app.object_storage import bucket
    from app.object_storage import client as s3
    from app.store import db

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    environment.update(PYTHONPATH=str(ROOT / "apps/api"), APP_ENV="development", PUBLIC_URL=origin,
                       COOKIE_SECURE="false", EMBEDDING_MODEL="", EMBEDDED_WORKER="false", EAGER_INGESTION="true")
    log_path = ROOT / "data/neon-e2e-server.log"
    log_path.parent.mkdir(exist_ok=True)
    report = {"ai_gateway": "unavailable_on_free_plan"}
    auth_user = document = conversation = app_user = organization = object_key = None
    process = None
    with log_path.open("w", encoding="utf-8") as logs:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--no-access-log"], cwd=ROOT, env=environment, stdout=logs, stderr=logs)
        try:
            with httpx.Client(base_url=origin, timeout=45) as app:
                deadline = time.monotonic() + 90
                while True:
                    try:
                        ready = app.get("/api/v1/health/ready")
                        if ready.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("Local app startup failed; inspect private data/neon-e2e-server.log")
                    time.sleep(.3)
                report["postgres"] = ready.json()["database"]
                report["revision"] = ready.json()["revision"]
                assert report["postgres"] == "postgresql" and report["revision"] == "0007"
                assert app.get("/api/v1/documents").status_code == 401
                email = "knowra-e2e-" + secrets.token_hex(6) + "@example.test"
                password = secrets.token_urlsafe(30)
                auth_url = os.environ["NEON_AUTH_BASE_URL"].rstrip("/") + "/"
                with httpx.Client(base_url=auth_url, headers={"Origin": f"http://localhost:{port}"}, timeout=30) as auth:
                    signup = auth.post("sign-up/email", json={"email": email, "password": password, "name": "Fictional integration test"})
                    signup.raise_for_status()
                    auth_user = signup.json().get("user", {}).get("id")
                    signin = auth.post("sign-in/email", json={"email": email, "password": password})
                    signin.raise_for_status()
                    token_response = auth.get("token")
                    token_response.raise_for_status()
                    token = token_response.json()["token"]
                    exchange = app.post("/api/v1/auth/neon", json={"token": token, "workspace": "Fictional Neon E2E"})
                    exchange.raise_for_status()
                    user = app.get("/api/v1/users/me").json()
                    app_user, organization = user["id"], user["org"]
                    report["auth_signup_signin_jwt_session"] = "passed"
                    original = b"FICTIONAL TEST DATA. Annual leave allowance is 24 days in 2026, compared with 20 days in 2025."
                    upload = app.post("/api/v1/documents", files={"file": ("fictional-neon-test.txt", original, "text/plain")})
                    upload.raise_for_status()
                    document, version = upload.json()["id"], upload.json()["version_id"]
                    downloaded = app.get(f"/api/v1/documents/{document}/versions/{version}/original")
                    downloaded.raise_for_status()
                    assert downloaded.content == original
                    with db() as connection:
                        row = connection.execute("SELECT original,original_key FROM document_versions WHERE id=?", (version,)).fetchone()
                        assert row["original"] is None and row["original_key"]
                        object_key = row["original_key"]
                    report["private_storage_upload_download_checksum"] = "passed"
                    integrity = app.get(f"/api/v1/documents/{document}/versions/{version}/integrity")
                    integrity.raise_for_status()
                    assert integrity.json()["verified"] and integrity.json()["checksum"] == hashlib.sha256(original).hexdigest()
                    assert integrity.json()["storage"] == "neon"
                    assert httpx.get(os.environ["NEON_FUNCTION_HELLO_BASE_URL"], timeout=30).status_code == 401
                    report["function_permission_check_and_original_integrity"] = "passed"
                    conversation = app.post("/api/v1/conversations").json()["id"]
                    answer = app.post(f"/api/v1/conversations/{conversation}/messages", json={"content": "How many days did annual leave increase? Cite the source."})
                    answer.raise_for_status()
                    assert answer.json()["citations"]
                    report["cited_answer"] = answer.json()["mode"]
                    auth.post("sign-out", json={}).raise_for_status()
                    app.post("/api/v1/auth/logout").raise_for_status()
                    assert app.get("/api/v1/documents").status_code == 401
                    report["logout_protected_access"] = "passed"
        finally:
            if process:
                process.terminate()
                process.wait(timeout=15)
            # Delete only exact identifiers generated by this invocation.
            if app_user:
                with db() as connection:
                    if conversation:
                        connection.execute("DELETE FROM conversations WHERE id=? AND user_id=?", (conversation, app_user))
                    if document:
                        connection.execute("DELETE FROM documents WHERE id=? AND owner=?", (document, app_user))
                    connection.execute("DELETE FROM sessions WHERE user_id=?", (app_user,))
                    connection.execute("DELETE FROM external_identities WHERE user_id=?", (app_user,))
                    connection.execute("DELETE FROM audit WHERE actor=?", (app_user,))
                    connection.execute("DELETE FROM users WHERE id=?", (app_user,))
                    connection.execute("DELETE FROM organizations WHERE id=?", (organization,))
            if object_key:
                s3().delete_object(Bucket=bucket(), Key=object_key)
            if auth_user:
                deleted = subprocess.run([shutil.which("neon.cmd") or "neon", "neon-auth", "user", "delete", auth_user], cwd=ROOT, capture_output=True, text=True, timeout=30)
                report["test_identity_cleanup"] = "passed" if deleted.returncode == 0 else "requires_cleanup"
    target = ROOT / "evals/neon-live-report.json"
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
