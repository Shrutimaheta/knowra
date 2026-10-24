"""Managed identity bindings and immutable object storage references."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade():
    op.create_table(
        "external_identities",
        sa.Column("provider", sa.Text, primary_key=True),
        sa.Column("subject", sa.Text, primary_key=True),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    )
    op.add_column("document_versions", sa.Column("original_key", sa.Text))
    op.add_column("document_versions", sa.Column("original_size", sa.Integer))


def downgrade():
    raise RuntimeError("Restore a matching backup; identity and source references must be preserved.")
