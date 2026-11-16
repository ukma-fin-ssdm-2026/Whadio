"""Remember the preset and the requester of a notes job a member asked for.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("processing_job", sa.Column("template", sa.String(length=9), nullable=True))
    op.add_column("processing_job", sa.Column("requested_by_user_id", sa.Uuid(), nullable=True))
    op.create_check_constraint(
        "template", "processing_job", "template IN ('summary', 'detailed', 'interview')"
    )
    op.create_check_constraint(
        "notes_request",
        "processing_job",
        "job_type = 'notes' OR (template IS NULL AND requested_by_user_id IS NULL)",
    )
    op.create_foreign_key(
        op.f("fk_processing_job_requested_by_user_id_user"),
        "processing_job",
        "user",
        ["requested_by_user_id"],
        ["user_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM processing_job
                WHERE template IS NOT NULL OR requested_by_user_id IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'Downgrade would lose requested notes jobs';
            END IF;
        END $$;
        """
    )
    op.drop_constraint(
        op.f("fk_processing_job_requested_by_user_id_user"), "processing_job", type_="foreignkey"
    )
    op.drop_constraint(op.f("ck_processing_job_notes_request"), "processing_job", type_="check")
    op.drop_constraint(op.f("ck_processing_job_template"), "processing_job", type_="check")
    op.drop_column("processing_job", "requested_by_user_id")
    op.drop_column("processing_job", "template")
