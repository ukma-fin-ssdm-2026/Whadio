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
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, MappedColumn

from ..accounts.enums import LlmProvider, NotesTemplate
from ..shared.database import Base, enum_type
from .enums import (
    AccessMode,
    MeetingSource,
    ProcessingFailure,
    ProcessingState,
    RecordingStatus,
    RevisionType,
)


class Folder(Base):
    __tablename__: str = "folder"

    folder_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("workspace.workspace_id", ondelete="CASCADE")
    )
    name: Mapped[str] = MappedColumn[str](Text)
    created_at: Mapped[datetime] = MappedColumn[datetime](
        DateTime(timezone=True), server_default=func.now()
    )
    is_default: Mapped[bool] = MappedColumn[bool](server_default=false())

    __table_args__: tuple[Constraint | Index, ...] = (
        Index("uq_folder_workspace_name", "workspace_id", func.lower(name), unique=True),
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
    source_type: Mapped[MeetingSource] = MappedColumn[MeetingSource](
        enum_type(MeetingSource, "source"),
    )
    recording_status: Mapped[RecordingStatus] = MappedColumn[RecordingStatus](
        enum_type(RecordingStatus, "recording_status"),
    )
    processing_state: Mapped[ProcessingState] = MappedColumn[ProcessingState](
        enum_type(ProcessingState, "processing_state"),
    )
    failure_reason: Mapped[ProcessingFailure | None] = MappedColumn[ProcessingFailure | None](
        enum_type(ProcessingFailure, "processing_failure"),
    )
    storage_path: Mapped[str | None] = MappedColumn[str | None](Text)
    duration_seconds: Mapped[int | None] = MappedColumn[int | None]()
    recorded_at: Mapped[datetime] = MappedColumn[datetime](DateTime(timezone=True))
    created_at: Mapped[datetime] = MappedColumn[datetime](
        DateTime(timezone=True), server_default=func.now()
    )
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
    recording_warning_sent_at: Mapped[datetime | None] = MappedColumn[datetime | None](
        DateTime(timezone=True)
    )
    access_mode: Mapped[AccessMode] = MappedColumn[AccessMode](
        enum_type(AccessMode, "access_mode"),
    )
    regeneration_count: Mapped[int] = MappedColumn[int](server_default=text("0"))

    __table_args__: tuple[Constraint | Index, ...] = (
        CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="duration"),
        CheckConstraint("regeneration_count >= 0", name="regeneration_count"),
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
    source_job_id: Mapped[UUID | None] = MappedColumn[UUID | None](unique=True)
    language: Mapped[str] = MappedColumn[str](Text)
    model_name: Mapped[str] = MappedColumn[str](Text)
    created_at: Mapped[datetime] = MappedColumn[datetime](
        DateTime(timezone=True), server_default=func.now()
    )
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
    revision_type: Mapped[RevisionType] = MappedColumn[RevisionType](
        enum_type(RevisionType, "revision_type"),
    )
    edited_by_user_id: Mapped[UUID | None] = MappedColumn[UUID | None](
        ForeignKey("user.user_id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = MappedColumn[datetime](
        DateTime(timezone=True), server_default=func.now()
    )
    # The trigger stamps the top-level transaction, including inserts inside savepoints.
    initialization_xid: Mapped[str] = MappedColumn[str](
        Text, server_default=text("pg_current_xact_id()::text")
    )

    __table_args__: tuple[Constraint | Index, ...] = (
        UniqueConstraint("transcript_id", "revision_id"),
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
    created_at: Mapped[datetime] = MappedColumn[datetime](
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__: tuple[Constraint | Index, ...] = (
        Index("uq_glossary_workspace_term", "workspace_id", func.lower(term), unique=True),
    )


class Note(Base):
    __tablename__: str = "note"

    note_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("meeting.meeting_id", ondelete="CASCADE")
    )
    template: Mapped[NotesTemplate] = MappedColumn[NotesTemplate](
        enum_type(NotesTemplate, "template"),
    )
    content: Mapped[str] = MappedColumn[str](Text)
    model_name: Mapped[str] = MappedColumn[str](Text)
    provider: Mapped[LlmProvider] = MappedColumn[LlmProvider](
        enum_type(LlmProvider, "provider"),
    )
    created_by_user_id: Mapped[UUID | None] = MappedColumn[UUID | None](
        ForeignKey("user.user_id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = MappedColumn[datetime](
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__: tuple[Constraint | Index, ...] = (
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


class RecordingDeletion(Base):
    __tablename__: str = "recording_deletion"

    deletion_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    storage_key: Mapped[str] = MappedColumn[str](Text, unique=True)
    created_at: Mapped[datetime] = MappedColumn[datetime](
        DateTime(timezone=True), server_default=func.now()
    )


class FolderRecovery(Base):
    __tablename__: str = "folder_recovery"

    folder_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True)
    workspace_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("workspace.workspace_id", ondelete="CASCADE")
    )
    name: Mapped[str] = MappedColumn[str](Text)
    created_at: Mapped[datetime] = MappedColumn[datetime](DateTime(timezone=True))
    deleted_at: Mapped[datetime] = MappedColumn[datetime](DateTime(timezone=True))


class FolderRecoveryMeeting(Base):
    __tablename__: str = "folder_recovery_meeting"

    folder_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("folder_recovery.folder_id", ondelete="CASCADE"), primary_key=True
    )
    meeting_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("meeting.meeting_id", ondelete="CASCADE"), primary_key=True
    )
