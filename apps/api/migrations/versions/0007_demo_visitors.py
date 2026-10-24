"""Isolated, expiring public-demo visitors and persistent request budgets."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade():
    op.create_table(
        "demo_visitors",
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("expires", sa.Float, nullable=False),
    )
    op.create_index("demo_visitors_expiry", "demo_visitors", ["expires"])
    op.create_table(
        "demo_usage",
        sa.Column("bucket", sa.Text, primary_key=True),
        sa.Column("period", sa.Text, primary_key=True),
        sa.Column("count", sa.Integer, nullable=False),
        sa.Column("expires", sa.Float, nullable=False),
    )
    op.create_index("demo_usage_expiry", "demo_usage", ["expires"])


def downgrade():
    raise RuntimeError("Restore a backup to preserve visitor records.")
