"""Queue a capture chunk's audio for deletion from storage when its row is deleted.

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Chunk rows go with their meeting through the foreign-key cascade, which no application
    # code sees, so the trigger is what keeps an unfinished capture's audio from outliving it.
    op.execute(
        """
        CREATE FUNCTION queue_capture_chunk_deletion() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            INSERT INTO recording_deletion (deletion_id, storage_key)
            VALUES (gen_random_uuid(), OLD.storage_key)
            ON CONFLICT (storage_key) DO NOTHING;
            RETURN OLD;
        END $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER capture_chunk_queue_deletion AFTER DELETE ON capture_chunk
        FOR EACH ROW EXECUTE FUNCTION queue_capture_chunk_deletion();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER capture_chunk_queue_deletion ON capture_chunk")
    op.execute("DROP FUNCTION queue_capture_chunk_deletion()")
