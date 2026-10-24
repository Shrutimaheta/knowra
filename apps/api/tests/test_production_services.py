import base64
import json
import subprocess
import time

import httpx
import pytest
from app import malware, parser_service, processing
from app.operations import status
from app.store import db
from app.worker import run_once
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_workflows import register, upload


class Scanner:
    def __init__(self, result):
        self.result = result
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def sendall(self, value):
        self.sent.append(value)

    def recv(self, size):
        result, self.result = self.result, b""
        return result


def test_scanner_uses_framed_stream_and_clean_result(monkeypatch):
    connection = Scanner(b"stream: OK\0")
    monkeypatch.setenv("CLAMAV_HOST", "private-scanner")
    monkeypatch.setattr(malware.socket, "create_connection", lambda *a, **k: connection)
    malware.scan(b"example content")
    assert connection.sent == [b"zINSTREAM\0", b"\0\0\0\x0fexample content", b"\0\0\0\0"]


@pytest.mark.parametrize("reply,code", [(b"stream: Test-Signature FOUND\0", 400), (b"stream: ERROR\0", 503), (b"", 503)])
def test_scanner_failures_reject_before_parsing(client, monkeypatch, reply, code):
    register(client)
    monkeypatch.setenv("CLAMAV_HOST", "scanner")
    monkeypatch.setattr(malware.socket, "create_connection", lambda *a, **k: Scanner(reply))

    def no_parse(*args):
        raise AssertionError("Rejected bytes must never enter a document parser")

    monkeypatch.setattr("app.main.validate", no_parse)
    response = client.post("/api/v1/documents", files={"file": ("test.txt", b"unsafe content")})
    assert response.status_code == code
    assert client.get("/api/v1/documents").json() == []


def test_production_cannot_silently_use_local_parser_or_skip_scanning(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("PARSER_URL", raising=False)
    monkeypatch.delenv("CLAMAV_HOST", raising=False)
    with pytest.raises(HTTPException, match="503"):
        malware.scan(b"text")
    with pytest.raises(HTTPException, match="503"):
        processing.validate("test.txt", b"text")


def test_parser_supervisor_runs_real_disposable_child():
    with TestClient(parser_service.app) as client:
        response = client.post("/process", json={
            "operation": "validate", "filename": "policy.txt",
            "data": base64.b64encode(b"Annual leave is 24 days.").decode(),
        })
        assert response.status_code == 200
        assert response.json() == {"pages": ["Annual leave is 24 days."]}
        invalid = client.post("/process", json={"operation": "arbitrary", "data": ""})
        assert invalid.status_code == 422


def test_parser_child_has_no_credentials_and_timeout_releases_slot(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "must-not-be-inherited")
    monkeypatch.setenv("DATABASE_URL", "private-database")

    def timeout(command, **options):
        assert "GEMINI_API_KEY" not in options["env"]
        assert "DATABASE_URL" not in options["env"]
        assert options["timeout"] == 300
        raise subprocess.TimeoutExpired(command, 300)

    monkeypatch.setattr(parser_service.subprocess, "run", timeout)
    with pytest.raises(HTTPException) as error:
        parser_service.supervise(b"{}")
    assert error.value.status_code == 422
    assert parser_service.slot.acquire(blocking=False)
    parser_service.slot.release()


def test_remote_parser_unavailable_never_falls_back_to_local(monkeypatch):
    monkeypatch.setenv("PARSER_URL", "http://parser:8001")

    def unavailable(*args, **kwargs):
        raise httpx.ConnectError("internal private details")

    monkeypatch.setattr(processing.httpx, "post", unavailable)
    with pytest.raises(HTTPException) as error:
        processing.validate("test.txt", b"content")
    assert error.value.status_code == 503
    assert "private details" not in error.value.detail


def test_worker_rechecks_files_and_permanently_rejects_malware(client, monkeypatch):
    register(client)
    monkeypatch.setenv("EAGER_INGESTION", "false")
    document = upload(client)

    def reject(data):
        raise HTTPException(400, "This file was rejected by malware scanning.")

    monkeypatch.setattr("app.worker.scan", reject)
    assert run_once()
    result = client.get("/api/v1/documents/" + document).json()
    assert result["status"] == "failed" and "malware" in result["error"]
    with db() as c:
        job = c.execute("SELECT status,attempts FROM ingestion_jobs").fetchone()
    assert job["status"] == "failed" and job["attempts"] == 1


def test_operational_checks_detect_backlog_and_backup_age(client, monkeypatch, tmp_path):
    register(client)
    monkeypatch.setenv("EAGER_INGESTION", "false")
    upload(client)
    marker = tmp_path / "last-success"
    marker.write_text(str(int(time.time()) - 100000))
    monkeypatch.setenv("BACKUP_SUCCESS_FILE", str(marker))
    monkeypatch.setenv("OPS_DISK_PATH", str(tmp_path))
    with db() as c:
        c.execute("UPDATE ingestion_jobs SET available=?", (time.time() - 1000,))
    result = status()
    assert {"ingestion_backlog", "stale_backup"} <= set(result["alerts"])
    marker.write_text(str(int(time.time())))
    assert "stale_backup" not in status()["alerts"]
    assert "private" not in json.dumps(result)
