"""Keep the reset email cooldown after the reset link is used.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("user", sa.Column("password_reset_mail_queued_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("user", "password_reset_mail_queued_at")
