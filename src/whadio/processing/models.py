from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Constraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
)
from sqlalchemy.orm import Mapped, MappedColumn

from ..shared.database import Base


class ProcessingJob(Base):
    __tablename__: str = "processing_job"

    processing_job_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("meeting.meeting_id", ondelete="CASCADE")
    )
    job_type: Mapped[str] = MappedColumn[str](Text)
    status: Mapped[str] = MappedColumn[str](Text)
    failure_reason: Mapped[str | None] = MappedColumn[str | None](Text)
    created_at: Mapped[datetime] = MappedColumn[datetime](DateTime(timezone=True))
    attempts: Mapped[int] = MappedColumn[int]()
    started_at: Mapped[datetime | None] = MappedColumn[datetime | None](DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = MappedColumn[datetime | None](DateTime(timezone=True))

    __table_args__: tuple[Constraint | Index, ...] = (
        CheckConstraint("job_type IN ('transcription', 'notes')", name="job_type"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="status"),
        CheckConstraint("attempts >= 0", name="attempts"),
        Index("ix_processing_job_meeting_id", "meeting_id"),
        Index("ix_processing_job_status_created", "status", "created_at"),
    )
