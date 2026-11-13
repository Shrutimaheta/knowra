"""Per-account sign-in failure tracking for temporary lockout."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade():
    op.create_table(
        "login_failures",
        # SHA-256 of the normalized email, so the table holds no addresses.
        sa.Column("account", sa.Text, primary_key=True),
        sa.Column("failures", sa.Integer, nullable=False),
        sa.Column("first_failure", sa.Float, nullable=False),
        sa.Column("locked_until", sa.Float, nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_table("login_failures")
