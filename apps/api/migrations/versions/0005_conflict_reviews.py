"""Version-bound, personal conflict review decisions."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade():
    op.create_table(
        "conflict_reviews",
        sa.Column(
            "user_id",
            sa.Text,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("fingerprint", sa.Text, primary_key=True),
        sa.Column(
            "org",
            sa.Text,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "left_version",
            sa.Text,
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "right_version",
            sa.Text,
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "preferred_version",
            sa.Text,
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
        ),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("updated", sa.Text, nullable=False),
        sa.CheckConstraint(
            "status IN ('open','authoritative','dismissed')",
            name="conflict_review_status",
        ),
    )


def downgrade():
    raise RuntimeError("Restore a backup to preserve saved review decisions.")
