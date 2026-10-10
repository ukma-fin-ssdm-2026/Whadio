"""Enforce workspace folder names and preserve meetings when a folder is deleted."""

from pathlib import Path

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TRIGGER folder_preserve_meetings ON folder")
    op.execute("DROP FUNCTION preserve_folder_meetings()")
    op.drop_index("uq_folder_workspace_name", table_name="folder")
