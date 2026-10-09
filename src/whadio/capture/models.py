from datetime import datetime
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import (
    CheckConstraint,
    Constraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, MappedColumn

from ..shared.database import Base


class CaptureSession(Base):
    __tablename__: str = "capture_session"

    capture_session_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("meeting.meeting_id", ondelete="CASCADE")
    )
    opened_by_user_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("user.user_id", ondelete="RESTRICT")
    )
    status: Mapped[str] = MappedColumn[str](Text)
    last_chunk_seq: Mapped[int | None] = MappedColumn[int | None]()
    last_chunk_at: Mapped[datetime | None] = MappedColumn[datetime | None](DateTime(timezone=True))
    created_at: Mapped[datetime] = MappedColumn[datetime](DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = MappedColumn[datetime | None](DateTime(timezone=True))

    __table_args__: tuple[Constraint | Index, ...] = (
        UniqueConstraint("meeting_id"),
        CheckConstraint("status IN ('recording', 'idle', 'assembled', 'abandoned')", name="status"),
        CheckConstraint("last_chunk_seq IS NULL OR last_chunk_seq >= 0", name="sequence"),
        Index("ix_capture_session_status_last_chunk", "status", "last_chunk_at"),
    )


class CaptureChunk(Base):
    __tablename__: str = "capture_chunk"

    capture_chunk_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    capture_session_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("capture_session.capture_session_id", ondelete="CASCADE")
    )
    seq: Mapped[int] = MappedColumn[int]()
    storage_key: Mapped[str] = MappedColumn[str](Text)
    speaker_events: Mapped[JsonValue | None] = MappedColumn[JsonValue | None](
        JSONB(none_as_null=True), nullable=True
    )
    received_at: Mapped[datetime] = MappedColumn[datetime](DateTime(timezone=True))

    __table_args__: tuple[Constraint | Index, ...] = (
        UniqueConstraint("capture_session_id", "seq"),
        CheckConstraint("seq >= 0", name="sequence"),
    )
