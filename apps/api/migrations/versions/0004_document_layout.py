"""Preserve per-page OCR and table extraction details."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade():
    op.add_column(
        "document_versions",
        sa.Column("layout_meta", sa.Text(), nullable=False, server_default="[]"),
    )


def downgrade():
    op.drop_column("document_versions", "layout_meta")
