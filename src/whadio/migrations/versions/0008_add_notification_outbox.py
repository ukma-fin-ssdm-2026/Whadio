"""Reserve notification mail in an outbox that the scheduler sends from.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "notification_outbox",
        sa.Column("notice_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=26), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.CheckConstraint(
            "kind IN ('share_access_request', 'recording_deletion_warning', 'hosted_eviction', "
            "'processing_finished', 'processing_failed')",
            name=op.f("ck_notification_outbox_kind"),
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_notification_outbox_attempts")),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name=op.f("ck_notification_outbox_payload")
        ),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"],
            ["user.user_id"],
            name=op.f("fk_notification_outbox_recipient_user_id_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("notice_id", name=op.f("pk_notification_outbox")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_notification_outbox_dedupe_key")),
    )
    op.create_index(
        "ix_notification_outbox_recipient_user_id", "notification_outbox", ["recipient_user_id"]
    )
    op.create_index(
        "ix_notification_outbox_unsent",
        "notification_outbox",
        ["next_attempt_at"],
        postgresql_where=sa.text("sent_at IS NULL"),
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON notification_outbox TO whadio_app")


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM notification_outbox WHERE sent_at IS NULL) THEN
                RAISE EXCEPTION 'Downgrade would discard unsent notifications';
            END IF;
        END $$;
        """
    )
    op.drop_table("notification_outbox")
