"""Store sanitized failures, transcript job provenance and reversible folder deletion.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("meeting", sa.Column("failure_reason", sa.Text()))
    op.create_check_constraint(
        "processing_failure",
        "meeting",
        "failure_reason IS NULL OR failure_reason IN ('transcription_failed', 'notes_failed', "
        "'provider_unavailable', 'provider_rejected', 'processing_timeout')",
    )
    op.add_column("transcript", sa.Column("source_job_id", sa.Uuid()))
    op.create_unique_constraint(
        op.f("uq_transcript_source_job_id"), "transcript", ["source_job_id"]
    )
    op.create_table(
        "folder_recovery",
        sa.Column("folder_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspace.workspace_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "folder_recovery_meeting",
        sa.Column(
            "folder_id",
            sa.Uuid(),
            sa.ForeignKey("folder_recovery.folder_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "meeting_id",
            sa.Uuid(),
            sa.ForeignKey("meeting.meeting_id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON folder_recovery, "
        "folder_recovery_meeting TO whadio_app"
    )


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM folder_recovery)
               OR EXISTS (SELECT 1 FROM transcript WHERE source_job_id IS NOT NULL)
               OR EXISTS (SELECT 1 FROM meeting WHERE failure_reason IS NOT NULL) THEN
                RAISE EXCEPTION 'Downgrade would discard recovery or processing provenance';
            END IF;
        END $$;
    """)
    op.drop_table("folder_recovery_meeting")
    op.drop_table("folder_recovery")
    op.drop_constraint(op.f("uq_transcript_source_job_id"), "transcript", type_="unique")
    op.drop_column("transcript", "source_job_id")
    op.drop_constraint(op.f("ck_meeting_processing_failure"), "meeting", type_="check")
    op.drop_column("meeting", "failure_reason")
