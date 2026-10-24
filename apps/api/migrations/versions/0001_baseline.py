"""Baseline compatible with the original local application."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None


def upgrade():
    statements = [
        "CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL, password TEXT NOT NULL, org TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'owner')",
        "CREATE TABLE organizations (id TEXT PRIMARY KEY, name TEXT NOT NULL)",
        "CREATE TABLE sessions (token TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id), expires DOUBLE PRECISION NOT NULL)",
        "CREATE TABLE documents (id TEXT PRIMARY KEY, org TEXT NOT NULL, owner TEXT NOT NULL, title TEXT NOT NULL, category TEXT NOT NULL, visibility TEXT NOT NULL, status TEXT NOT NULL, content TEXT NOT NULL, error TEXT, created TEXT NOT NULL, version INTEGER DEFAULT 1)",
        "CREATE TABLE chunks (id TEXT PRIMARY KEY, document TEXT REFERENCES documents(id) ON DELETE CASCADE, content TEXT NOT NULL, page INTEGER NOT NULL)",
        "CREATE TABLE conversations (id TEXT PRIMARY KEY, org TEXT NOT NULL, user_id TEXT NOT NULL, title TEXT NOT NULL, created TEXT NOT NULL)",
        "CREATE TABLE messages (id TEXT PRIMARY KEY, conversation TEXT REFERENCES conversations(id) ON DELETE CASCADE, role TEXT NOT NULL, content TEXT NOT NULL, citations TEXT NOT NULL DEFAULT '[]', created TEXT NOT NULL, feedback INTEGER, latency INTEGER DEFAULT 0)",
        "CREATE TABLE audit (id TEXT PRIMARY KEY, org TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL, created TEXT NOT NULL)",
        "CREATE INDEX documents_org ON documents(org)",
        "CREATE INDEX chunks_document ON chunks(document)",
        "CREATE INDEX conversations_user ON conversations(user_id, org)",
    ]
    for statement in statements:
        op.execute(sa.text(statement))


def downgrade():
    raise RuntimeError(
        "Destructive downgrades are intentionally disabled; restore a backup."
    )
