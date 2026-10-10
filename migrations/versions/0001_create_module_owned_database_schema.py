"""Create module-owned database schema

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def _upgrade_identity() -> None:
    op.create_table(
        "pending_registration",
        sa.Column("pending_registration_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("expires_at > created_at", name=op.f("ck_pending_registration_expiry")),
        sa.PrimaryKeyConstraint("pending_registration_id", name=op.f("pk_pending_registration")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_pending_registration_token_hash")),
    )
    op.create_index(
        "ix_pending_registration_expires_at", "pending_registration", ["expires_at"], unique=False
    )
    op.create_index(
        "uq_pending_registration_email",
        "pending_registration",
        [sa.literal_column("lower(email)")],
        unique=True,
    )
    op.create_table(
        "user",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_administrator", sa.Boolean(), nullable=False),
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user")),
    )
    op.create_index("uq_user_email", "user", [sa.literal_column("lower(email)")], unique=True)
    op.create_table(
        "workspace",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("default_template", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_personal", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "default_template IN ('summary', 'detailed', 'interview')",
            name=op.f("ck_workspace_template"),
        ),
        sa.PrimaryKeyConstraint("workspace_id", name=op.f("pk_workspace")),
    )
    op.create_table(
        "audit_event",
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("meeting_id", sa.Uuid(), nullable=True),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "(workspace_id IS NULL) = (action IN ('mcp_key_created', 'mcp_key_revoked'))",
            name=op.f("ck_audit_event_workspace_scope"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["user.user_id"],
            name=op.f("fk_audit_event_actor_user_id_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("audit_event_id", name=op.f("pk_audit_event")),
    )
    op.create_index(
        "ix_audit_event_actor_occurred",
        "audit_event",
        ["actor_user_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_event_meeting_occurred",
        "audit_event",
        ["meeting_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_event_workspace_occurred",
        "audit_event",
        ["workspace_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "folder",
        sa.Column("folder_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspace.workspace_id"],
            name=op.f("fk_folder_workspace_id_workspace"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("folder_id", name=op.f("pk_folder")),
    )
    op.create_index("ix_folder_workspace_id", "folder", ["workspace_id"], unique=False)
    op.create_index(
        "uq_folder_default",
        "folder",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_table(
        "invitation",
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("invited_email", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("invited_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('Member', 'Moderator')", name=op.f("ck_invitation_role")),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'cancelled')",
            name=op.f("ck_invitation_status"),
        ),
        sa.CheckConstraint("expires_at > created_at", name=op.f("ck_invitation_expiry")),
        sa.ForeignKeyConstraint(
            ["invited_by_user_id"],
            ["user.user_id"],
            name=op.f("fk_invitation_invited_by_user_id_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspace.workspace_id"],
            name=op.f("fk_invitation_workspace_id_workspace"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("invitation_id", name=op.f("pk_invitation")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_invitation_token_hash")),
    )
    op.create_index("ix_invitation_expires_at", "invitation", ["expires_at"], unique=False)
    op.create_index(
        "ix_invitation_inviter_created",
        "invitation",
        ["invited_by_user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_invitation_workspace_email_created",
        "invitation",
        ["workspace_id", sa.literal_column("lower(invited_email)"), "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_invitation_pending",
        "invitation",
        ["workspace_id", sa.literal_column("lower(invited_email)")],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "llm_provider_config",
        sa.Column("provider_config_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "provider = 'Whadio' OR api_key_encrypted IS NOT NULL",
            name=op.f("ck_llm_provider_config_encrypted_key"),
        ),
        sa.CheckConstraint(
            "provider IN ('Whadio', 'Anthropic', 'OpenAI', 'Google')",
            name=op.f("ck_llm_provider_config_provider"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspace.workspace_id"],
            name=op.f("fk_llm_provider_config_workspace_id_workspace"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("provider_config_id", name=op.f("pk_llm_provider_config")),
        sa.UniqueConstraint("workspace_id", name=op.f("uq_llm_provider_config_workspace_id")),
    )
    op.create_table(
        "mcp_key",
        sa.Column("mcp_key_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at", name=op.f("ck_mcp_key_expiry")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.user_id"], name=op.f("fk_mcp_key_user_id_user"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("mcp_key_id", name=op.f("pk_mcp_key")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_mcp_key_key_hash")),
    )
    op.create_index("ix_mcp_key_user_id", "mcp_key", ["user_id"], unique=False)
    op.create_table(
        "password_reset",
        sa.Column("password_reset_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("expires_at > created_at", name=op.f("ck_password_reset_expiry")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.user_id"],
            name=op.f("fk_password_reset_user_id_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("password_reset_id", name=op.f("pk_password_reset")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_password_reset_token_hash")),
        sa.UniqueConstraint("user_id", name=op.f("uq_password_reset_user_id")),
    )
    op.create_index("ix_password_reset_expires_at", "password_reset", ["expires_at"], unique=False)
    op.create_table(
        "session",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('browser', 'extension')", name=op.f("ck_session_kind")),
        sa.CheckConstraint("expires_at > created_at", name=op.f("ck_session_expiry")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.user_id"], name=op.f("fk_session_user_id_user"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_session")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_session_token_hash")),
    )
    op.create_index("ix_session_expires_at", "session", ["expires_at"], unique=False)
    op.create_index("ix_session_user_id", "session", ["user_id"], unique=False)
    op.create_table(
        "workspace_membership",
        sa.Column("workspace_membership_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('Member', 'Moderator', 'Owner')", name=op.f("ck_workspace_membership_role")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.user_id"],
            name=op.f("fk_workspace_membership_user_id_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspace.workspace_id"],
            name=op.f("fk_workspace_membership_workspace_id_workspace"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_membership_id", name=op.f("pk_workspace_membership")),
        sa.UniqueConstraint(
            "workspace_id", "user_id", name=op.f("uq_workspace_membership_workspace_id")
        ),
    )
    op.create_index(
        "ix_workspace_membership_user_id", "workspace_membership", ["user_id"], unique=False
    )


def _upgrade_content() -> None:
    op.create_index(
        "uq_workspace_owner",
        "workspace_membership",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("role = 'Owner'"),
    )
    op.create_table(
        "meeting",
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("folder_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_is_generated", sa.Boolean(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("recording_status", sa.Text(), nullable=False),
        sa.Column("processing_state", sa.Text(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consent_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_confirmed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("recording_delete_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recording_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_mode", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "access_mode IN ('workspace', 'restricted')", name=op.f("ck_meeting_access_mode")
        ),
        sa.CheckConstraint(
            "processing_state IN ('recording', 'queued', 'processing', 'processed', 'failed')",
            name=op.f("ck_meeting_processing_state"),
        ),
        sa.CheckConstraint(
            "recording_status IN ('complete', 'partial')", name=op.f("ck_meeting_recording_status")
        ),
        sa.CheckConstraint(
            "source_type IN ('extension', 'upload')", name=op.f("ck_meeting_source")
        ),
        sa.CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0", name=op.f("ck_meeting_duration")
        ),
        sa.ForeignKeyConstraint(
            ["consent_confirmed_by_user_id"],
            ["user.user_id"],
            name=op.f("fk_meeting_consent_confirmed_by_user_id_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["user.user_id"],
            name=op.f("fk_meeting_created_by_user_id_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["folder_id"],
            ["folder.folder_id"],
            name=op.f("fk_meeting_folder_id_folder"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("meeting_id", name=op.f("pk_meeting")),
    )
    op.create_index("ix_meeting_created_at", "meeting", ["created_at", "meeting_id"], unique=False)
    op.create_index(
        "ix_meeting_folder_recorded",
        "meeting",
        ["folder_id", "recorded_at", "meeting_id"],
        unique=False,
    )
    op.create_index(
        "ix_meeting_retention",
        "meeting",
        ["recording_delete_after"],
        unique=False,
        postgresql_where=sa.text("recording_deleted_at IS NULL"),
    )
    op.create_table(
        "capture_session",
        sa.Column("capture_session_id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("opened_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("last_chunk_seq", sa.Integer(), nullable=True),
        sa.Column("last_chunk_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('recording', 'idle', 'assembled', 'abandoned')",
            name=op.f("ck_capture_session_status"),
        ),
        sa.CheckConstraint(
            "last_chunk_seq IS NULL OR last_chunk_seq >= 0",
            name=op.f("ck_capture_session_sequence"),
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["meeting.meeting_id"],
            name=op.f("fk_capture_session_meeting_id_meeting"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["opened_by_user_id"],
            ["user.user_id"],
            name=op.f("fk_capture_session_opened_by_user_id_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("capture_session_id", name=op.f("pk_capture_session")),
        sa.UniqueConstraint("meeting_id", name=op.f("uq_capture_session_meeting_id")),
    )
    op.create_index(
        "ix_capture_session_status_last_chunk",
        "capture_session",
        ["status", "last_chunk_at"],
        unique=False,
    )
    op.create_table(
        "external_share",
        sa.Column("share_id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("redact_speaker_names", sa.Boolean(), nullable=False),
        sa.Column("include_recording", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "NOT include_recording", name=op.f("ck_external_share_read_only_content")
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["user.user_id"],
            name=op.f("fk_external_share_created_by_user_id_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["meeting.meeting_id"],
            name=op.f("fk_external_share_meeting_id_meeting"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"],
            ["user.user_id"],
            name=op.f("fk_external_share_recipient_user_id_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("share_id", name=op.f("pk_external_share")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_external_share_token_hash")),
    )
    op.create_index("ix_external_share_meeting_id", "external_share", ["meeting_id"], unique=False)
    op.create_index(
        "ix_external_share_recipient_user_id", "external_share", ["recipient_user_id"], unique=False
    )
    op.create_table(
        "glossary_term",
        sa.Column("term_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("term", sa.Text(), nullable=False),
        sa.Column("preferred_form", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("source_meeting_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["user.user_id"],
            name=op.f("fk_glossary_term_created_by_user_id_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_meeting_id"],
            ["meeting.meeting_id"],
            name=op.f("fk_glossary_term_source_meeting_id_meeting"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspace.workspace_id"],
            name=op.f("fk_glossary_term_workspace_id_workspace"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("term_id", name=op.f("pk_glossary_term")),
        sa.UniqueConstraint("workspace_id", "term", name=op.f("uq_glossary_term_workspace_id")),
    )
    op.create_table(
        "meeting_access_grant",
        sa.Column("access_grant_id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("granted_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"],
            ["user.user_id"],
            name=op.f("fk_meeting_access_grant_granted_by_user_id_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["meeting.meeting_id"],
            name=op.f("fk_meeting_access_grant_meeting_id_meeting"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.user_id"],
            name=op.f("fk_meeting_access_grant_user_id_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("access_grant_id", name=op.f("pk_meeting_access_grant")),
        sa.UniqueConstraint(
            "meeting_id", "user_id", name=op.f("uq_meeting_access_grant_meeting_id")
        ),
    )
    op.create_index(
        "ix_meeting_access_grant_user_id", "meeting_access_grant", ["user_id"], unique=False
    )
    op.create_table(
        "note",
        sa.Column("note_id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "provider IN ('Whadio', 'Anthropic', 'OpenAI', 'Google')", name=op.f("ck_note_provider")
        ),
        sa.CheckConstraint(
            "template IN ('summary', 'detailed', 'interview')", name=op.f("ck_note_template")
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["user.user_id"],
            name=op.f("fk_note_created_by_user_id_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["meeting.meeting_id"],
            name=op.f("fk_note_meeting_id_meeting"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("note_id", name=op.f("pk_note")),
    )
    op.create_index("ix_note_meeting_created", "note", ["meeting_id", "created_at"], unique=False)
    op.create_table(
        "processing_job",
        sa.Column("processing_job_id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "job_type IN ('transcription', 'notes')", name=op.f("ck_processing_job_job_type")
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name=op.f("ck_processing_job_status"),
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_processing_job_attempts")),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["meeting.meeting_id"],
            name=op.f("fk_processing_job_meeting_id_meeting"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("processing_job_id", name=op.f("pk_processing_job")),
    )
    op.create_index("ix_processing_job_meeting_id", "processing_job", ["meeting_id"], unique=False)
    op.create_index(
        "ix_processing_job_status_created", "processing_job", ["status", "created_at"], unique=False
    )
    op.create_table(
        "transcript",
        sa.Column("transcript_id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_revision_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["meeting.meeting_id"],
            name=op.f("fk_transcript_meeting_id_meeting"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["transcript_id", "current_revision_id"],
            ["transcript_revision.transcript_id", "transcript_revision.revision_id"],
            name="fk_transcript_current_revision",
            initially="DEFERRED",
            deferrable=True,
            use_alter=True,
        ),
        sa.PrimaryKeyConstraint("transcript_id", name=op.f("pk_transcript")),
        sa.UniqueConstraint("meeting_id", name=op.f("uq_transcript_meeting_id")),
    )
    op.create_table(
        "capture_chunk",
        sa.Column("capture_chunk_id", sa.Uuid(), nullable=False),
        sa.Column("capture_session_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("speaker_events", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("seq >= 0", name=op.f("ck_capture_chunk_sequence")),
        sa.ForeignKeyConstraint(
            ["capture_session_id"],
            ["capture_session.capture_session_id"],
            name=op.f("fk_capture_chunk_capture_session_id_capture_session"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("capture_chunk_id", name=op.f("pk_capture_chunk")),
        sa.UniqueConstraint(
            "capture_session_id", "seq", name=op.f("uq_capture_chunk_capture_session_id")
        ),
    )
    op.create_table(
        "note_context_meeting",
        sa.Column("note_context_meeting_id", sa.Uuid(), nullable=False),
        sa.Column("note_id", sa.Uuid(), nullable=False),
        sa.Column("context_meeting_id", sa.Uuid(), nullable=True),
        sa.Column("context_meeting_name_snapshot", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["context_meeting_id"],
            ["meeting.meeting_id"],
            name=op.f("fk_note_context_meeting_context_meeting_id_meeting"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["note_id"],
            ["note.note_id"],
            name=op.f("fk_note_context_meeting_note_id_note"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("note_context_meeting_id", name=op.f("pk_note_context_meeting")),
        sa.UniqueConstraint(
            "note_id", "context_meeting_id", name=op.f("uq_note_context_meeting_note_id")
        ),
    )
    op.create_index(
        "ix_note_context_meeting_context_meeting_id",
        "note_context_meeting",
        ["context_meeting_id"],
        unique=False,
    )
    op.create_table(
        "share_access_request",
        sa.Column("share_access_request_id", sa.Uuid(), nullable=False),
        sa.Column("share_id", sa.Uuid(), nullable=False),
        sa.Column("requester_user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'declined')",
            name=op.f("ck_share_access_request_status"),
        ),
        sa.ForeignKeyConstraint(
            ["requester_user_id"],
            ["user.user_id"],
            name=op.f("fk_share_access_request_requester_user_id_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["share_id"],
            ["external_share.share_id"],
            name=op.f("fk_share_access_request_share_id_external_share"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("share_access_request_id", name=op.f("pk_share_access_request")),
        sa.UniqueConstraint(
            "share_id", "requester_user_id", name=op.f("uq_share_access_request_share_id")
        ),
    )
    op.create_index(
        "uq_share_access_request_approved",
        "share_access_request",
        ["share_id"],
        unique=True,
        postgresql_where=sa.text("status = 'approved'"),
    )
    op.create_table(
        "transcript_revision",
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("transcript_id", sa.Uuid(), nullable=False),
        sa.Column("revision_type", sa.Text(), nullable=False),
        sa.Column("edited_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "revision_type IN ('original', 'edited')",
            name=op.f("ck_transcript_revision_revision_type"),
        ),
        sa.ForeignKeyConstraint(
            ["edited_by_user_id"],
            ["user.user_id"],
            name=op.f("fk_transcript_revision_edited_by_user_id_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transcript_id"],
            ["transcript.transcript_id"],
            name=op.f("fk_transcript_revision_transcript_id_transcript"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("revision_id", name=op.f("pk_transcript_revision")),
        sa.UniqueConstraint(
            "transcript_id", "revision_id", name=op.f("uq_transcript_revision_transcript_id")
        ),
    )
    op.create_index(
        "uq_transcript_original",
        "transcript_revision",
        ["transcript_id"],
        unique=True,
        postgresql_where=sa.text("revision_type = 'original'"),
    )
    op.create_table(
        "speaker",
        sa.Column("speaker_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["transcript_revision.revision_id"],
            name=op.f("fk_speaker_revision_id_transcript_revision"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("speaker_id", name=op.f("pk_speaker")),
        sa.UniqueConstraint("revision_id", "speaker_id", name=op.f("uq_speaker_revision_id")),
    )
    op.create_table(
        "transcript_segment",
        sa.Column("segment_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("speaker_id", sa.Uuid(), nullable=True),
        sa.Column("start_time_seconds", sa.Numeric(), nullable=False),
        sa.Column("end_time_seconds", sa.Numeric(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "start_time_seconds >= 0 AND start_time_seconds < end_time_seconds",
            name=op.f("ck_transcript_segment_time_interval"),
        ),
        sa.ForeignKeyConstraint(
            ["revision_id", "speaker_id"],
            ["speaker.revision_id", "speaker.speaker_id"],
            name=op.f("fk_transcript_segment_revision_id_speaker"),
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["transcript_revision.revision_id"],
            name=op.f("fk_transcript_segment_revision_id_transcript_revision"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("segment_id", name=op.f("pk_transcript_segment")),
    )
    op.create_index(
        "ix_transcript_segment_revision_time",
        "transcript_segment",
        ["revision_id", "start_time_seconds"],
        unique=False,
    )


def upgrade() -> None:
    _upgrade_identity()
    _upgrade_content()
    op.create_check_constraint(
        op.f("ck_audit_event_action"),
        "audit_event",
        "action IN ('meeting_created', "
        "'meeting_renamed', "
        "'meeting_moved', "
        "'meeting_deleted', "
        "'meeting_evicted', "
        "'transcript_edited', "
        "'speaker_renamed', "
        "'notes_regenerated', "
        "'meeting_restricted', "
        "'meeting_unrestricted', "
        "'access_granted', "
        "'access_revoked', "
        "'share_created', "
        "'share_revoked', "
        "'share_access_approved', "
        "'share_access_declined', "
        "'member_invited', "
        "'invitation_cancelled', "
        "'member_joined', "
        "'member_removed', "
        "'member_role_changed', "
        "'workspace_deleted', "
        "'provider_configured', "
        "'mcp_key_created', "
        "'mcp_key_revoked')",
    )
    op.create_foreign_key(
        "fk_transcript_current_revision",
        "transcript",
        "transcript_revision",
        ["transcript_id", "current_revision_id"],
        ["transcript_id", "revision_id"],
        deferrable=True,
        initially="DEFERRED",
    )


def _downgrade_identity() -> None:
    op.drop_index("ix_transcript_segment_revision_time", table_name="transcript_segment")
    op.drop_table("transcript_segment")
    op.drop_table("speaker")
    op.drop_index(
        "uq_transcript_original",
        table_name="transcript_revision",
        postgresql_where=sa.text("revision_type = 'original'"),
    )
    op.drop_table("transcript_revision")
    op.drop_index(
        "uq_share_access_request_approved",
        table_name="share_access_request",
        postgresql_where=sa.text("status = 'approved'"),
    )
    op.drop_table("share_access_request")
    op.drop_index("ix_note_context_meeting_context_meeting_id", table_name="note_context_meeting")
    op.drop_table("note_context_meeting")
    op.drop_table("capture_chunk")
    op.drop_table("transcript")
    op.drop_index("ix_processing_job_status_created", table_name="processing_job")
    op.drop_index("ix_processing_job_meeting_id", table_name="processing_job")
    op.drop_table("processing_job")
    op.drop_index("ix_note_meeting_created", table_name="note")
    op.drop_table("note")
    op.drop_index("ix_meeting_access_grant_user_id", table_name="meeting_access_grant")
    op.drop_table("meeting_access_grant")
    op.drop_table("glossary_term")
    op.drop_index("ix_external_share_recipient_user_id", table_name="external_share")
    op.drop_index("ix_external_share_meeting_id", table_name="external_share")
    op.drop_table("external_share")
    op.drop_index("ix_capture_session_status_last_chunk", table_name="capture_session")
    op.drop_table("capture_session")
    op.drop_index(
        "ix_meeting_retention",
        table_name="meeting",
        postgresql_where=sa.text("recording_deleted_at IS NULL"),
    )
    op.drop_index("ix_meeting_folder_recorded", table_name="meeting")
    op.drop_index("ix_meeting_created_at", table_name="meeting")
    op.drop_table("meeting")


def _downgrade_content() -> None:
    op.drop_index(
        "uq_workspace_owner",
        table_name="workspace_membership",
        postgresql_where=sa.text("role = 'Owner'"),
    )
    op.drop_index("ix_workspace_membership_user_id", table_name="workspace_membership")
    op.drop_table("workspace_membership")
    op.drop_index("ix_session_user_id", table_name="session")
    op.drop_index("ix_session_expires_at", table_name="session")
    op.drop_table("session")
    op.drop_index("ix_password_reset_expires_at", table_name="password_reset")
    op.drop_table("password_reset")
    op.drop_index("ix_mcp_key_user_id", table_name="mcp_key")
    op.drop_table("mcp_key")
    op.drop_table("llm_provider_config")
    op.drop_index(
        "uq_invitation_pending",
        table_name="invitation",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_index("ix_invitation_workspace_email_created", table_name="invitation")
    op.drop_index("ix_invitation_inviter_created", table_name="invitation")
    op.drop_index("ix_invitation_expires_at", table_name="invitation")
    op.drop_table("invitation")
    op.drop_index("uq_folder_default", table_name="folder", postgresql_where=sa.text("is_default"))
    op.drop_index("ix_folder_workspace_id", table_name="folder")
    op.drop_table("folder")
    op.drop_index("ix_audit_event_workspace_occurred", table_name="audit_event")
    op.drop_index("ix_audit_event_meeting_occurred", table_name="audit_event")
    op.drop_index("ix_audit_event_actor_occurred", table_name="audit_event")
    op.drop_table("audit_event")
    op.drop_table("workspace")
    op.drop_index("uq_user_email", table_name="user")
    op.drop_table("user")
    op.drop_index("uq_pending_registration_email", table_name="pending_registration")
    op.drop_index("ix_pending_registration_expires_at", table_name="pending_registration")
    op.drop_table("pending_registration")


def downgrade() -> None:
    op.drop_constraint("fk_transcript_current_revision", "transcript", type_="foreignkey")
    _downgrade_identity()
    _downgrade_content()
