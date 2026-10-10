from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Constraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, MappedColumn

from ..shared.database import Base, enum_values
from .enums import JobStatus, JobType


class ProcessingJob(Base):
    __tablename__: str = "processing_job"

    processing_job_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("meeting.meeting_id", ondelete="CASCADE")
    )
    job_type: Mapped[JobType] = MappedColumn[JobType](
        Enum(
            JobType,
            name="job_type",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            validate_strings=True,
        ),
    )
    status: Mapped[JobStatus] = MappedColumn[JobStatus](
        Enum(
            JobStatus,
            name="status",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            validate_strings=True,
        ),
    )
    failure_reason: Mapped[str | None] = MappedColumn[str | None](Text)
    created_at: Mapped[datetime] = MappedColumn[datetime](
        DateTime(timezone=True), server_default=func.now()
    )
    attempts: Mapped[int] = MappedColumn[int](server_default=text("0"))
    started_at: Mapped[datetime | None] = MappedColumn[datetime | None](DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = MappedColumn[datetime | None](DateTime(timezone=True))

    __table_args__: tuple[Constraint | Index, ...] = (
        CheckConstraint("attempts >= 0", name="attempts"),
        Index("ix_processing_job_meeting_id", "meeting_id"),
        Index("ix_processing_job_status_created", "status", "created_at"),
    )
