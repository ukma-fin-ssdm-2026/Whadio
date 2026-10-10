"""Align enum storage, composite names and server defaults with typed models."""

import sqlalchemy as sa
from alembic import op

revision: str = "0004r"
down_revision: str | None = "0004"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None

_ENUM_COLUMNS: tuple[tuple[str, str, int], ...] = (
    ("audit_event", "action", 21),
    ("capture_session", "status", 9),
    ("invitation", "role", 9),
    ("invitation", "status", 9),
    ("llm_provider_config", "provider", 9),
    ("meeting", "access_mode", 10),
    ("meeting", "processing_state", 10),
    ("meeting", "recording_status", 8),
    ("meeting", "source_type", 9),
    ("note", "provider", 9),
    ("note", "template", 9),
    ("processing_job", "job_type", 13),
    ("processing_job", "status", 9),
    ("session", "kind", 9),
    ("share_access_request", "status", 8),
    ("transcript_revision", "revision_type", 8),
    ("workspace", "default_template", 9),
    ("workspace_membership", "role", 9),
)

_DEFAULTS: tuple[tuple[str, str, str], ...] = (
    ("audit_event", "occurred_at", "now()"),
    ("capture_chunk", "received_at", "now()"),
    ("capture_session", "created_at", "now()"),
    ("external_share", "created_at", "now()"),
    ("external_share", "redact_speaker_names", "false"),
    ("folder", "created_at", "now()"),
    ("folder", "is_default", "false"),
    ("glossary_term", "created_at", "now()"),
    ("invitation", "created_at", "now()"),
    ("llm_provider_config", "created_at", "now()"),
    ("mcp_key", "created_at", "now()"),
    ("meeting", "created_at", "now()"),
    ("meeting_access_grant", "granted_at", "now()"),
    ("note", "created_at", "now()"),
    ("password_reset", "created_at", "now()"),
    ("pending_registration", "created_at", "now()"),
    ("processing_job", "attempts", "0"),
    ("processing_job", "created_at", "now()"),
    ("session", "created_at", "now()"),
    ("share_access_request", "requested_at", "now()"),
    ("transcript", "created_at", "now()"),
    ("transcript_revision", "created_at", "now()"),
    ("user", "created_at", "now()"),
    ("user", "is_administrator", "false"),
    ("workspace", "created_at", "now()"),
    ("workspace", "is_personal", "false"),
    ("workspace_membership", "joined_at", "now()"),
)

_RENAMES: tuple[tuple[str, str, str], ...] = (
    (
        "capture_chunk",
        "uq_capture_chunk_capture_session_id",
        "uq_capture_chunk_capture_session_id_seq",
    ),
    ("glossary_term", "uq_glossary_term_workspace_id", "uq_glossary_term_workspace_id_term"),
    (
        "meeting_access_grant",
        "uq_meeting_access_grant_meeting_id",
        "uq_meeting_access_grant_meeting_id_user_id",
    ),
    (
        "note_context_meeting",
        "uq_note_context_meeting_note_id",
        "uq_note_context_meeting_note_id_context_meeting_id",
    ),
    (
        "share_access_request",
        "uq_share_access_request_share_id",
        "uq_share_access_request_share_id_requester_user_id",
    ),
    ("speaker", "uq_speaker_revision_id", "uq_speaker_revision_id_speaker_id"),
    (
        "transcript_revision",
        "uq_transcript_revision_transcript_id",
        "uq_transcript_revision_transcript_id_revision_id",
    ),
    (
        "transcript_segment",
        "fk_transcript_segment_revision_id_speaker",
        "fk_transcript_segment_revision_id_speaker_id_speaker",
    ),
    (
        "workspace_membership",
        "uq_workspace_membership_workspace_id",
        "uq_workspace_membership_workspace_id_user_id",
    ),
)


def upgrade() -> None:
    for table, column, length in _ENUM_COLUMNS:
        op.alter_column(table, column, existing_type=sa.Text(), type_=sa.String(length))
    for table, column, expression in _DEFAULTS:
        op.alter_column(table, column, server_default=sa.text(expression))
    for table, old, new in _RENAMES:
        op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{old}" TO "{new}"')
    op.drop_index("ix_folder_workspace_id", table_name="folder")
    op.execute("DROP TRIGGER meeting_access_integrity ON meeting")
    op.execute(
        "CREATE CONSTRAINT TRIGGER meeting_access_integrity "
        "AFTER INSERT OR DELETE OR UPDATE OF access_mode, folder_id ON meeting "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_meeting_access()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER meeting_access_integrity ON meeting")
    op.execute(
        "CREATE CONSTRAINT TRIGGER meeting_access_integrity "
        "AFTER INSERT OR UPDATE OR DELETE ON meeting "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_meeting_access()"
    )
    op.create_index("ix_folder_workspace_id", "folder", ["workspace_id"])
    for table, old, new in reversed(_RENAMES):
        op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{new}" TO "{old}"')
    for table, column, _ in _DEFAULTS:
        op.alter_column(table, column, server_default=None)
    for table, column, length in _ENUM_COLUMNS:
        op.alter_column(table, column, existing_type=sa.String(length), type_=sa.Text())
