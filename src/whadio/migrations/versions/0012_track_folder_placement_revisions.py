"""Track the exact folder placement a conditional move expects.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "meeting",
        sa.Column(
            "folder_revision_id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
    )


def downgrade() -> None:
    op.drop_column("meeting", "folder_revision_id")
