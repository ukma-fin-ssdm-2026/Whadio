"""Remove the unused share flag and give each integrity trigger its own function."""

from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "0004t"
down_revision: str | None = "0004s"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None

_TRIGGERS: tuple[tuple[str, str, str, str], ...] = (
    ("folder", "folder_workspace", "UPDATE OF workspace_id", "prevent_folder_workspace_move"),
    ("meeting", "meeting_workspace", "UPDATE OF folder_id", "prevent_meeting_workspace_move"),
    (
        "transcript_revision",
        "original_revision_immutable",
        "UPDATE OR DELETE",
        "protect_original_revision_row",
    ),
    (
        "transcript_segment",
        "original_segment_immutable",
        "INSERT OR UPDATE OR DELETE",
        "protect_original_segment",
    ),
    (
        "speaker",
        "original_speaker_immutable",
        "INSERT OR UPDATE OR DELETE",
        "protect_original_speaker",
    ),
)


def upgrade() -> None:
    op.drop_constraint(op.f("ck_external_share_read_only_content"), "external_share", type_="check")
    op.drop_column("external_share", "include_recording")
    for table, trigger, _, _ in _TRIGGERS:
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
    op.execute("DROP FUNCTION prevent_cross_workspace_move()")
    op.execute("DROP FUNCTION protect_original_revision()")
    op.execute(Path(__file__).with_suffix(".sql").read_text(encoding="utf-8"))
    for table, trigger, events, function in _TRIGGERS:
        op.execute(
            f"CREATE TRIGGER {trigger} BEFORE {events} ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {function}()"
        )


def downgrade() -> None:
    for table, trigger, _, function in _TRIGGERS:
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
        op.execute(f"DROP FUNCTION {function}()")
    op.execute(Path(__file__).with_name("0004t_previous_functions.sql").read_text(encoding="utf-8"))
    for table, trigger, events, _ in _TRIGGERS:
        function = (
            "prevent_cross_workspace_move"
            if table in ("folder", "meeting")
            else "protect_original_revision"
        )
        op.execute(
            f"CREATE TRIGGER {trigger} BEFORE {events} ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {function}()"
        )
    op.add_column(
        "external_share",
        sa.Column("include_recording", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("external_share", "include_recording", server_default=None)
    op.create_check_constraint(
        op.f("ck_external_share_read_only_content"), "external_share", "NOT include_recording"
    )
