"""Mail registration links, password resets and sign-in reminders through the outbox.

Revision ID: 0014
Revises: 0013
"""

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_notification_outbox_kind"), "notification_outbox", type_="check")
    op.create_check_constraint(
        "kind",
        "notification_outbox",
        "kind IN ('share_access_request', 'recording_deletion_warning', 'hosted_eviction', "
        "'processing_finished', 'processing_failed', 'registration_link', 'password_reset', "
        "'sign_in_reminder')",
    )
    op.alter_column("notification_outbox", "recipient_user_id", nullable=True)
    op.create_check_constraint(
        "recipient",
        "notification_outbox",
        "(recipient_user_id IS NULL) = (kind = 'registration_link')",
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM notification_outbox
                WHERE kind IN ('registration_link', 'password_reset', 'sign_in_reminder')
                AND sent_at IS NULL
            ) THEN
                RAISE EXCEPTION 'Downgrade would discard unsent account links';
            END IF;
        END $$;
        """
    )
    op.execute(
        "DELETE FROM notification_outbox "
        "WHERE kind IN ('registration_link', 'password_reset', 'sign_in_reminder')"
    )
    op.drop_constraint(
        op.f("ck_notification_outbox_recipient"), "notification_outbox", type_="check"
    )
    op.alter_column("notification_outbox", "recipient_user_id", nullable=False)
    op.drop_constraint(op.f("ck_notification_outbox_kind"), "notification_outbox", type_="check")
    op.create_check_constraint(
        "kind",
        "notification_outbox",
        "kind IN ('share_access_request', 'recording_deletion_warning', 'hosted_eviction', "
        "'processing_finished', 'processing_failed')",
    )
