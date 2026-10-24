import os
from uuid import uuid4

import pytest
from app.main import app
from app.store import initialize
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


@pytest.fixture(autouse=True)
def postgres_test_schema(monkeypatch):
    """CI can run the same workflows against an isolated real PostgreSQL schema."""
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        yield
        return
    schema = "test_" + uuid4().hex
    administrator = create_engine(url)
    with administrator.begin() as c:
        c.execute(text("CREATE SCHEMA " + schema))
    scoped = make_url(url).update_query_dict(
        {"options": "-csearch_path=" + schema + ",public"}
    )
    monkeypatch.setenv("DATABASE_URL", scoped.render_as_string(hide_password=False))
    try:
        yield
    finally:
        with administrator.begin() as c:
            c.execute(text("DROP SCHEMA " + schema + " CASCADE"))
        administrator.dispose()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL_UNPOOLED", raising=False)
    monkeypatch.setenv("KNOWRA_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("EMBEDDED_WORKER", "false")
    monkeypatch.setenv("EAGER_INGESTION", "true")
    monkeypatch.setenv("EMBEDDING_MODEL", "")
    monkeypatch.setenv("MAIL_OUTBOX", str(tmp_path / "outbox"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    initialize()
    with TestClient(app) as client:
        yield client
