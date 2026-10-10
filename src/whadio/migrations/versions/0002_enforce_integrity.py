"""Enforce cross-row invariants and append-only audit privileges."""

from pathlib import Path

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP FUNCTION check_workspace_integrity() CASCADE")
    op.execute("DROP FUNCTION check_meeting_access() CASCADE")
    op.execute("DROP FUNCTION check_membership_access() CASCADE")
    op.execute("DROP FUNCTION assert_meeting_access(uuid) CASCADE")
    op.execute("DROP FUNCTION prevent_cross_workspace_move() CASCADE")
    op.execute("DROP FUNCTION check_transcript_original() CASCADE")
    op.execute("DROP FUNCTION protect_original_revision() CASCADE")
    op.execute("DROP FUNCTION reject_personal_invitation() CASCADE")
    op.execute("GRANT UPDATE, DELETE ON audit_event TO whadio_app")
