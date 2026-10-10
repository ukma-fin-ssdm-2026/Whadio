from datetime import datetime
from typing import final
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, MappedColumn

from ..core.db import Base, UtcDateTime
from .schemas import AccessMode, ProcessingState, RecordingStatus, RevisionType, SourceType


@final
class Folder(Base):
    __tablename__ = "folders"

    folder_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = MappedColumn[UUID](ForeignKey("workspaces.workspace_id"))
    name: Mapped[str] = MappedColumn[str](String(100))
    created_at: Mapped[datetime] = MappedColumn[datetime](UtcDateTime)
    is_default: Mapped[bool] = MappedColumn[bool]()


@final
class Meeting(Base):
    __tablename__ = "meetings"

    meeting_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    folder_id: Mapped[UUID] = MappedColumn[UUID](ForeignKey("folders.folder_id"))
    created_by_user_id: Mapped[UUID] = MappedColumn[UUID](ForeignKey("users.user_id"))
    name: Mapped[str] = MappedColumn[str](String(200))
    name_is_generated: Mapped[bool] = MappedColumn[bool]()
    source_type: Mapped[SourceType] = MappedColumn[SourceType]()
    recording_status: Mapped[RecordingStatus] = MappedColumn[RecordingStatus]()
    processing_state: Mapped[ProcessingState] = MappedColumn[ProcessingState]()
    storage_path: Mapped[str | None] = MappedColumn[str | None](String(500))
    duration_seconds: Mapped[int | None] = MappedColumn[int | None]()
    recorded_at: Mapped[datetime] = MappedColumn[datetime](UtcDateTime)
    created_at: Mapped[datetime] = MappedColumn[datetime](UtcDateTime)
    consent_confirmed_at: Mapped[datetime | None] = MappedColumn[datetime | None](UtcDateTime)
    consent_confirmed_by_user_id: Mapped[UUID | None] = MappedColumn[UUID | None](
        ForeignKey("users.user_id")
    )
    recording_delete_after: Mapped[datetime] = MappedColumn[datetime](UtcDateTime)
    recording_deleted_at: Mapped[datetime | None] = MappedColumn[datetime | None](UtcDateTime)
    access_mode: Mapped[AccessMode] = MappedColumn[AccessMode]()


@final
class Transcript(Base):
    __tablename__ = "transcripts"

    transcript_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = MappedColumn[UUID](ForeignKey("meetings.meeting_id"), unique=True)
    language: Mapped[str] = MappedColumn[str](String(16))
    model_name: Mapped[str] = MappedColumn[str](String(100))
    created_at: Mapped[datetime] = MappedColumn[datetime](UtcDateTime)
    # Transcripts and revisions point at each other: the key is added after both tables exist
    # and checked only at commit, so a transcript and its first revision go in together.
    current_revision_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey(
            "transcript_revisions.revision_id",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        )
    )


@final
class TranscriptRevision(Base):
    __tablename__ = "transcript_revisions"

    revision_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    transcript_id: Mapped[UUID] = MappedColumn[UUID](ForeignKey("transcripts.transcript_id"))
    revision_type: Mapped[RevisionType] = MappedColumn[RevisionType]()
    edited_by_user_id: Mapped[UUID | None] = MappedColumn[UUID | None](ForeignKey("users.user_id"))
    created_at: Mapped[datetime] = MappedColumn[datetime](UtcDateTime)


@final
class Speaker(Base):
    __tablename__ = "speakers"

    speaker_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    revision_id: Mapped[UUID] = MappedColumn[UUID](ForeignKey("transcript_revisions.revision_id"))
    display_name: Mapped[str] = MappedColumn[str](String(100))


@final
class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    segment_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    revision_id: Mapped[UUID] = MappedColumn[UUID](ForeignKey("transcript_revisions.revision_id"))
    speaker_id: Mapped[UUID | None] = MappedColumn[UUID | None](ForeignKey("speakers.speaker_id"))
    start_time_seconds: Mapped[float] = MappedColumn[float]()
    end_time_seconds: Mapped[float] = MappedColumn[float]()
    text: Mapped[str] = MappedColumn[str](Text)
