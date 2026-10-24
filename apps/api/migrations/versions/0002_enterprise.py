"""Immutable sources, durable jobs, security tokens and operational controls."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade():
    op.create_table(
        "document_versions",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column(
            "document",
            sa.Text,
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer, nullable=False),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("original", sa.LargeBinary),
        sa.Column("checksum", sa.Text, nullable=False),
        sa.Column("pages", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("created", sa.Text, nullable=False),
        sa.UniqueConstraint("document", "number"),
    )
    op.add_column("chunks", sa.Column("version_id", sa.Text))
    op.add_column("chunks", sa.Column("embedding", sa.Text))
    op.add_column("chunks", sa.Column("embedding_model", sa.Text))
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column(
            "version_id",
            sa.Text,
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("available", sa.Float, nullable=False),
        sa.Column("lease_until", sa.Float),
        sa.Column("lease_token", sa.Text),
        sa.Column("error", sa.Text),
    )
    op.create_index("jobs_pending", "ingestion_jobs", ["status", "available"])
    op.create_table(
        "account_tokens",
        sa.Column("token", sa.Text, primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("org", sa.Text),
        sa.Column("email", sa.Text),
        sa.Column("role", sa.Text),
        sa.Column("expires", sa.Float, nullable=False),
        sa.Column("used", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column("sessions", sa.Column("created", sa.Text))
    op.add_column("sessions", sa.Column("agent", sa.Text))
    op.add_column("messages", sa.Column("model", sa.Text))
    op.add_column(
        "messages", sa.Column("tokens", sa.Integer, nullable=False, server_default="0")
    )
    op.create_table(
        "request_limits",
        sa.Column("bucket", sa.Text, primary_key=True),
        sa.Column("window", sa.Integer, primary_key=True),
        sa.Column("count", sa.Integer, nullable=False),
    )
    op.create_table(
        "chat_runs",
        sa.Column(
            "conversation",
            sa.Text,
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("token", sa.Text, nullable=False),
        sa.Column("expires", sa.Float, nullable=False),
    )
    op.create_index("versions_document", "document_versions", ["document"])


def downgrade():
    raise RuntimeError(
        "Destructive downgrades are intentionally disabled; restore a backup."
    )
