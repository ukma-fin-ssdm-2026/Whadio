from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Constraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, MappedColumn

from ..shared.database import Base, enum_values
from .enums import ShareRequestStatus


class MeetingAccessGrant(Base):
    __tablename__: str = "meeting_access_grant"

    access_grant_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("meeting.meeting_id", ondelete="CASCADE")
    )
    user_id: Mapped[UUID] = MappedColumn[UUID](ForeignKey("user.user_id", ondelete="RESTRICT"))
    granted_by_user_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("user.user_id", ondelete="RESTRICT")
    )
    granted_at: Mapped[datetime] = MappedColumn[datetime](
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__: tuple[Constraint | Index, ...] = (
        UniqueConstraint("meeting_id", "user_id"),
        Index("ix_meeting_access_grant_user_id", "user_id"),
    )


class ExternalShare(Base):
    __tablename__: str = "external_share"

    share_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("meeting.meeting_id", ondelete="CASCADE")
    )
    created_by_user_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("user.user_id", ondelete="RESTRICT")
    )
    token_hash: Mapped[str] = MappedColumn[str](Text)
    redact_speaker_names: Mapped[bool] = MappedColumn[bool](server_default=false())
    created_at: Mapped[datetime] = MappedColumn[datetime](
        DateTime(timezone=True), server_default=func.now()
    )
    recipient_user_id: Mapped[UUID | None] = MappedColumn[UUID | None](
        ForeignKey("user.user_id", ondelete="RESTRICT")
    )
    revoked_at: Mapped[datetime | None] = MappedColumn[datetime | None](DateTime(timezone=True))

    __table_args__: tuple[Constraint | Index, ...] = (
        UniqueConstraint("token_hash"),
        Index("ix_external_share_meeting_id", "meeting_id"),
        Index("ix_external_share_recipient_user_id", "recipient_user_id"),
    )


class ShareAccessRequest(Base):
    __tablename__: str = "share_access_request"

    share_access_request_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    share_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("external_share.share_id", ondelete="CASCADE")
    )
    requester_user_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("user.user_id", ondelete="RESTRICT")
    )
    status: Mapped[ShareRequestStatus] = MappedColumn[ShareRequestStatus](
        Enum(
            ShareRequestStatus,
            name="status",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            validate_strings=True,
        ),
    )
    requested_at: Mapped[datetime] = MappedColumn[datetime](
        DateTime(timezone=True), server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = MappedColumn[datetime | None](DateTime(timezone=True))

    __table_args__: tuple[Constraint | Index, ...] = (
        UniqueConstraint("share_id", "requester_user_id"),
        Index(
            "uq_share_access_request_approved",
            "share_id",
            unique=True,
            postgresql_where=text("status = 'approved'"),
        ),
    )
