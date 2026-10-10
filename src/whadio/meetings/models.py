from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Constraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, MappedColumn

from ..shared.database import Base


class Folder(Base):
    __tablename__: str = "folder"

    folder_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("workspace.workspace_id", ondelete="CASCADE")
    )
    name: Mapped[str] = MappedColumn[str](Text)
    created_at: Mapped[datetime] = MappedColumn[datetime](DateTime(timezone=True))
    is_default: Mapped[bool] = MappedColumn[bool]()

    __table_args__: tuple[Constraint | Index, ...] = (
        Index("ix_folder_workspace_id", "workspace_id"),
        Index("uq_folder_workspace_name", "workspace_id", text("lower(name)"), unique=True),
        Index(
            "uq_folder_default", "workspace_id", unique=True, postgresql_where=text("is_default")
        ),
    )


class Meeting(Base):
    __tablename__: str = "meeting"

    meeting_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    folder_id: Mapped[UUID] = MappedColumn[UUID](ForeignKey("folder.folder_id", ondelete="CASCADE"))
    created_by_user_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("user.user_id", ondelete="RESTRICT")
    )
    name: Mapped[str] = MappedColumn[str](Text)
    name_is_generated: Mapped[bool] = MappedColumn[bool]()
    source_type: Mapped[str] = MappedColumn[str](Text)
    recording_status: Mapped[str] = MappedColumn[str](Text)
    processing_state: Mapped[str] = MappedColumn[str](Text)
    storage_path: Mapped[str | None] = MappedColumn[str | None](Text)
    duration_seconds: Mapped[int | None] = MappedColumn[int | None]()
    recorded_at: Mapped[datetime] = MappedColumn[datetime](DateTime(timezone=True))
    created_at: Mapped[datetime] = MappedColumn[datetime](DateTime(timezone=True))
    consent_confirmed_at: Mapped[datetime | None] = MappedColumn[datetime | None](
        DateTime(timezone=True)
    )
    consent_confirmed_by_user_id: Mapped[UUID | None] = MappedColumn[UUID | None](
        ForeignKey("user.user_id", ondelete="RESTRICT")
    )
    recording_delete_after: Mapped[datetime] = MappedColumn[datetime](DateTime(timezone=True))
    recording_deleted_at: Mapped[datetime | None] = MappedColumn[datetime | None](
        DateTime(timezone=True)
    )
    access_mode: Mapped[str] = MappedColumn[str](Text)

    __table_args__: tuple[Constraint | Index, ...] = (
        CheckConstraint("source_type IN ('extension', 'upload')", name="source"),
        CheckConstraint("recording_status IN ('complete', 'partial')", name="recording_status"),
        CheckConstraint(
            "processing_state IN ('recording', 'queued', 'processing', 'processed', 'failed')",
            name="processing_state",
        ),
        CheckConstraint("access_mode IN ('workspace', 'restricted')", name="access_mode"),
        CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="duration"),
        Index("ix_meeting_folder_recorded", "folder_id", "recorded_at", "meeting_id"),
        Index("ix_meeting_created_at", "created_at", "meeting_id"),
        Index(
            "ix_meeting_retention",
            "recording_delete_after",
            postgresql_where=text("recording_deleted_at IS NULL"),
        ),
    )


class Transcript(Base):
    __tablename__: str = "transcript"

    transcript_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("meeting.meeting_id", ondelete="CASCADE")
    )
    language: Mapped[str] = MappedColumn[str](Text)
    model_name: Mapped[str] = MappedColumn[str](Text)
    created_at: Mapped[datetime] = MappedColumn[datetime](DateTime(timezone=True))
    current_revision_id: Mapped[UUID] = MappedColumn[UUID]()

    __table_args__: tuple[Constraint | Index, ...] = (
        UniqueConstraint("meeting_id"),
        ForeignKeyConstraint(
            ["transcript_id", "current_revision_id"],
            ["transcript_revision.transcript_id", "transcript_revision.revision_id"],
            name="fk_transcript_current_revision",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
    )


class TranscriptRevision(Base):
    __tablename__: str = "transcript_revision"

    revision_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    transcript_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("transcript.transcript_id", ondelete="CASCADE")
    )
    revision_type: Mapped[str] = MappedColumn[str](Text)
    edited_by_user_id: Mapped[UUID | None] = MappedColumn[UUID | None](
        ForeignKey("user.user_id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = MappedColumn[datetime](DateTime(timezone=True))
    # The trigger stamps the top-level transaction, including inserts inside savepoints.
    initialization_xid: Mapped[str] = MappedColumn[str](
        Text, server_default=text("pg_current_xact_id()::text")
    )

    __table_args__: tuple[Constraint | Index, ...] = (
        UniqueConstraint("transcript_id", "revision_id"),
        CheckConstraint("revision_type IN ('original', 'edited')", name="revision_type"),
        Index(
            "uq_transcript_original",
            "transcript_id",
            unique=True,
            postgresql_where=text("revision_type = 'original'"),
        ),
    )


class Speaker(Base):
    __tablename__: str = "speaker"

    speaker_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    revision_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("transcript_revision.revision_id", ondelete="CASCADE")
    )
    display_name: Mapped[str] = MappedColumn[str](Text)

    __table_args__: tuple[Constraint | Index, ...] = (
        UniqueConstraint("revision_id", "speaker_id"),
    )


class TranscriptSegment(Base):
    __tablename__: str = "transcript_segment"

    segment_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    revision_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("transcript_revision.revision_id", ondelete="CASCADE")
    )
    speaker_id: Mapped[UUID | None] = MappedColumn[UUID | None]()
    start_time_seconds: Mapped[Decimal] = MappedColumn[Decimal](Numeric)
    end_time_seconds: Mapped[Decimal] = MappedColumn[Decimal](Numeric)
    text: Mapped[str] = MappedColumn[str](Text)

    __table_args__: tuple[Constraint | Index, ...] = (
        ForeignKeyConstraint(
            ["revision_id", "speaker_id"], ["speaker.revision_id", "speaker.speaker_id"]
        ),
        CheckConstraint(
            "start_time_seconds >= 0 AND start_time_seconds < end_time_seconds",
            name="time_interval",
        ),
        Index("ix_transcript_segment_revision_time", "revision_id", "start_time_seconds"),
    )


class GlossaryTerm(Base):
    __tablename__: str = "glossary_term"

    term_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("workspace.workspace_id", ondelete="CASCADE")
    )
    term: Mapped[str] = MappedColumn[str](Text)
    preferred_form: Mapped[str] = MappedColumn[str](Text)
    description: Mapped[str] = MappedColumn[str](Text)
    created_by_user_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("user.user_id", ondelete="RESTRICT")
    )
    source_meeting_id: Mapped[UUID | None] = MappedColumn[UUID | None](
        ForeignKey("meeting.meeting_id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = MappedColumn[datetime](DateTime(timezone=True))

    __table_args__: tuple[Constraint | Index, ...] = (UniqueConstraint("workspace_id", "term"),)


class Note(Base):
    __tablename__: str = "note"

    note_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("meeting.meeting_id", ondelete="CASCADE")
    )
    template: Mapped[str] = MappedColumn[str](Text)
    content: Mapped[str] = MappedColumn[str](Text)
    model_name: Mapped[str] = MappedColumn[str](Text)
    provider: Mapped[str] = MappedColumn[str](Text)
    created_by_user_id: Mapped[UUID | None] = MappedColumn[UUID | None](
        ForeignKey("user.user_id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = MappedColumn[datetime](DateTime(timezone=True))

    __table_args__: tuple[Constraint | Index, ...] = (
        CheckConstraint("template IN ('summary', 'detailed', 'interview')", name="template"),
        CheckConstraint("provider IN ('Whadio', 'Anthropic', 'OpenAI', 'Google')", name="provider"),
        Index("ix_note_meeting_created", "meeting_id", "created_at"),
    )


class NoteContextMeeting(Base):
    __tablename__: str = "note_context_meeting"

    note_context_meeting_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    note_id: Mapped[UUID] = MappedColumn[UUID](ForeignKey("note.note_id", ondelete="CASCADE"))
    context_meeting_id: Mapped[UUID | None] = MappedColumn[UUID | None](
        ForeignKey("meeting.meeting_id", ondelete="SET NULL")
    )
    context_meeting_name_snapshot: Mapped[str] = MappedColumn[str](Text)

    __table_args__: tuple[Constraint | Index, ...] = (
        UniqueConstraint("note_id", "context_meeting_id"),
        Index("ix_note_context_meeting_context_meeting_id", "context_meeting_id"),
    )
