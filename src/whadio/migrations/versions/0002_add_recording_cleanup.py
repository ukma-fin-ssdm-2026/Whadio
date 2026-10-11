"""Persist recording warnings, cleanup jobs and glossary uniqueness.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM glossary_term
                GROUP BY workspace_id, lower(term) HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION 'Resolve case-insensitive glossary duplicates before upgrading';
            END IF;
        END $$;
        """
    )
    op.add_column("meeting", sa.Column("recording_warning_sent_at", sa.DateTime(timezone=True)))
    op.drop_constraint("uq_glossary_term_workspace_id_term", "glossary_term", type_="unique")
    op.create_index(
        "uq_glossary_workspace_term",
        "glossary_term",
        ["workspace_id", sa.literal_column("lower(term)")],
        unique=True,
    )
    op.create_table(
        "recording_deletion",
        sa.Column("deletion_id", sa.Uuid(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("deletion_id", name=op.f("pk_recording_deletion")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_recording_deletion_storage_key")),
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON recording_deletion TO whadio_app")


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM recording_deletion) THEN
                RAISE EXCEPTION 'Drain pending recording cleanup before downgrading';
            END IF;
        END $$;
        """
    )
    op.drop_table("recording_deletion")
    op.drop_index("uq_glossary_workspace_term", table_name="glossary_term")
    op.create_unique_constraint(
        "uq_glossary_term_workspace_id_term", "glossary_term", ["workspace_id", "term"]
    )
    op.drop_column("meeting", "recording_warning_sent_at")
