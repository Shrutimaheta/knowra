import importlib.util
from pathlib import Path

import pytest
from alembic import command
from app.store import db, engine, initialize, migration_config


def test_legacy_migration_preserves_accounts_and_citations(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("KNOWRA_DB", str(tmp_path / "legacy.db"))
    command.upgrade(migration_config(), "0001")
    with db() as c:
        c.execute(
            "INSERT INTO users VALUES ('user','legacy@example.test','Legacy','salt:hash','org','owner')"
        )
        c.execute("INSERT INTO organizations VALUES ('org','Legacy workspace')")
        c.execute(
            "INSERT INTO documents (id,org,owner,title,category,visibility,status,content,created) VALUES ('doc','org','user','policy.txt','General','workspace','ready','Old policy text','2026-01-01')"
        )
        c.execute(
            "INSERT INTO chunks (id,document,content,page) VALUES ('chunk','doc','Old policy text',2)"
        )
        c.execute(
            "INSERT INTO conversations VALUES ('chat','org','user','Old chat','2026-01-01')"
        )
        c.execute(
            "INSERT INTO messages (id,conversation,role,content,citations,created) VALUES (?,?,?,?,?,?)",
            (
                "message",
                "chat",
                "assistant",
                "Old answer",
                '[{"document":"doc","id":"chunk","page":2,"content":"Old policy text"}]',
                "2026-01-01",
            ),
        )
    # Simulate the original unversioned database, where no Alembic tracking existed.
    with engine().begin() as c:
        from sqlalchemy import text

        c.execute(text("DROP TABLE alembic_version"))
    initialize()
    initialize()
    with db() as c:
        assert (
            c.execute("SELECT email FROM users").fetchone()["email"]
            == "legacy@example.test"
        )
        version = c.execute("SELECT * FROM document_versions").fetchone()
        import json

        assert json.loads(version["pages"])[1] == "Old policy text"
        assert version["original"] is None
        citations = json.loads(
            c.execute("SELECT citations FROM messages").fetchone()["citations"]
        )
        assert citations[0]["version_id"] == version["id"]


def test_backup_restore_roundtrip_to_empty_database(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("KNOWRA_DB", str(tmp_path / "source.db"))
    initialize()
    with db() as c:
        c.execute("INSERT INTO organizations VALUES ('org','Preserved workspace')")
        c.execute(
            "INSERT INTO users VALUES ('user','backup@example.test','Backup','hashed-secret','org','owner')"
        )
    script = Path(__file__).resolve().parents[3] / "scripts/backup.py"
    spec = importlib.util.spec_from_file_location("knowra_backup", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    backup = tmp_path / "backup.json.gz"
    module.backup(backup)
    with pytest.raises(ValueError):
        module.backup(backup)
    monkeypatch.setenv("KNOWRA_DB", str(tmp_path / "restored.db"))
    module.restore(backup)
    with db() as c:
        assert (
            c.execute("SELECT email FROM users").fetchone()["email"]
            == "backup@example.test"
        )
    with pytest.raises(ValueError):
        module.restore(backup)
