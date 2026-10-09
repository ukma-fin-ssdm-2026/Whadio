from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, UtcDateTime
from .schemas import AccessMode, ProcessingState, RecordingStatus, RevisionType, SourceType


class Folder(Base):
    __tablename__ = "folders"

    folder_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.workspace_id"))
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    is_default: Mapped[bool]


class Meeting(Base):
    __tablename__ = "meetings"

    meeting_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    folder_id: Mapped[UUID] = mapped_column(ForeignKey("folders.folder_id"))
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.user_id"))
    name: Mapped[str] = mapped_column(String(200))
    name_is_generated: Mapped[bool]
    source_type: Mapped[SourceType]
    recording_status: Mapped[RecordingStatus]
    processing_state: Mapped[ProcessingState]
    storage_path: Mapped[str | None] = mapped_column(String(500))
    duration_seconds: Mapped[int | None]
    recorded_at: Mapped[datetime] = mapped_column(UtcDateTime)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    consent_confirmed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    consent_confirmed_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.user_id"))
    recording_delete_after: Mapped[datetime] = mapped_column(UtcDateTime)
    recording_deleted_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    access_mode: Mapped[AccessMode]


class Transcript(Base):
    __tablename__ = "transcripts"

    transcript_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = mapped_column(ForeignKey("meetings.meeting_id"), unique=True)
    language: Mapped[str] = mapped_column(String(16))
    model_name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    # Transcripts and revisions point at each other: the key is added after both tables exist
    # and checked only at commit, so a transcript and its first revision go in together.
    current_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "transcript_revisions.revision_id",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        )
    )


class TranscriptRevision(Base):
    __tablename__ = "transcript_revisions"

    revision_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    transcript_id: Mapped[UUID] = mapped_column(ForeignKey("transcripts.transcript_id"))
    revision_type: Mapped[RevisionType]
    edited_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.user_id"))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class Speaker(Base):
    __tablename__ = "speakers"

    speaker_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    revision_id: Mapped[UUID] = mapped_column(ForeignKey("transcript_revisions.revision_id"))
    display_name: Mapped[str] = mapped_column(String(100))


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    segment_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    revision_id: Mapped[UUID] = mapped_column(ForeignKey("transcript_revisions.revision_id"))
    speaker_id: Mapped[UUID | None] = mapped_column(ForeignKey("speakers.speaker_id"))
    start_time_seconds: Mapped[float]
    end_time_seconds: Mapped[float]
    text: Mapped[str] = mapped_column(Text)
