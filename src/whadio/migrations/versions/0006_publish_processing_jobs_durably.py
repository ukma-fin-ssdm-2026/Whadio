"""Record which processing jobs are published and the context a notes job was sent.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Jobs queued before this revision are left unpublished, so one lost after its commit is
    # published again.
    op.add_column(
        "processing_job", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("processing_job", sa.Column("sent_context", postgresql.JSONB(), nullable=True))
    op.create_index(
        "ix_processing_job_unpublished",
        "processing_job",
        ["created_at"],
        postgresql_where=sa.text("status = 'queued' AND published_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_processing_job_unpublished", table_name="processing_job")
    op.drop_column("processing_job", "sent_context")
    op.drop_column("processing_job", "published_at")
