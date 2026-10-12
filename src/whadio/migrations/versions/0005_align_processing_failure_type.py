"""Align the branch-added failure column with its validated ORM enum.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.alter_column("meeting", "failure_reason", existing_type=sa.Text(), type_=sa.String(20))


def downgrade() -> None:
    op.alter_column("meeting", "failure_reason", existing_type=sa.String(20), type_=sa.Text())
