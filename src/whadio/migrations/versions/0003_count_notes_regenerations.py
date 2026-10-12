"""Count requested regenerations, including failed runs.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "meeting", sa.Column("regeneration_count", sa.Integer(), nullable=False, server_default="0")
    )
    op.execute(
        """
        UPDATE meeting SET regeneration_count = (
            SELECT count(*) FROM note
            WHERE note.meeting_id = meeting.meeting_id AND note.created_by_user_id IS NOT NULL
        )
        """
    )
    op.create_check_constraint("regeneration_count", "meeting", "regeneration_count >= 0")


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM meeting WHERE regeneration_count > 0) THEN
                RAISE EXCEPTION 'Downgrade would lose regeneration limits';
            END IF;
        END $$;
        """
    )
    op.drop_constraint(op.f("ck_meeting_regeneration_count"), "meeting", type_="check")
    op.drop_column("meeting", "regeneration_count")
