"""Track the current queue period without inventing historical retry timing."""

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "processing_job", sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("UPDATE processing_job SET queued_at = created_at WHERE attempts = 0")
    op.alter_column("processing_job", "queued_at", server_default=sa.func.now())
    op.execute("UPDATE processing_job SET started_at = NULL WHERE status = 'queued'")


def downgrade() -> None:
    op.drop_column("processing_job", "queued_at")
