"""Store the optional preset for an uploaded meeting's first notes.

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
    op.add_column("meeting", sa.Column("initial_notes_template", sa.String(length=9)))
    op.create_check_constraint(
        "initial_notes_template",
        "meeting",
        "initial_notes_template IN ('summary', 'detailed', 'interview')",
    )


def downgrade() -> None:
    op.execute("LOCK TABLE meeting IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM meeting
                WHERE initial_notes_template IS NOT NULL
                  AND processing_state IN ('queued', 'processing')
            ) THEN
                RAISE EXCEPTION 'Downgrade would discard pending upload presets';
            END IF;
        END $$;
    """)
    op.drop_constraint(op.f("ck_meeting_initial_notes_template"), "meeting", type_="check")
    op.drop_column("meeting", "initial_notes_template")
