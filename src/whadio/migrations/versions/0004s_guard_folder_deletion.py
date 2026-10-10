"""Require the Meetings service to move and audit meetings before deleting a folder."""

from pathlib import Path

from alembic import op

revision: str = "0004s"
down_revision: str | None = "0004r"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION preserve_folder_meetings() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
            PERFORM 1 FROM workspace WHERE workspace_id = OLD.workspace_id FOR UPDATE;
            IF NOT FOUND THEN RETURN OLD; END IF;
            IF OLD.is_default THEN
                RAISE EXCEPTION 'Default folder cannot be deleted' USING ERRCODE = '23514';
            END IF;
            IF EXISTS (SELECT 1 FROM meeting WHERE folder_id = OLD.folder_id) THEN
                RAISE EXCEPTION 'Move and audit meetings before deleting their folder'
                    USING ERRCODE = '23514';
            END IF;
            RETURN OLD;
        END $$;
    """)


def downgrade() -> None:
    original = (
        Path(__file__).with_name("0004_preserve_folder_meetings.sql").read_text(encoding="utf-8")
    )
    function = original.split("CREATE FUNCTION", 1)[1].split("CREATE TRIGGER", 1)[0]
    op.execute("CREATE OR REPLACE FUNCTION" + function)
