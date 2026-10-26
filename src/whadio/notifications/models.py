from datetime import datetime
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import (
    CheckConstraint,
    Constraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, MappedColumn

from ..shared.database import Base, enum_type
from .templates import NoticeKind

LAST_ERROR_LENGTH = 200


class NotificationOutbox(Base):
    __tablename__: str = "notification_outbox"

    notice_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    kind: Mapped[NoticeKind] = MappedColumn[NoticeKind](enum_type(NoticeKind, "kind"))
    recipient_user_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("user.user_id", ondelete="CASCADE")
    )
    dedupe_key: Mapped[str] = MappedColumn[str](Text)
    payload: Mapped[dict[str, JsonValue]] = MappedColumn[dict[str, JsonValue]](JSONB)
    created_at: Mapped[datetime] = MappedColumn[datetime](
        DateTime(timezone=True), server_default=func.now()
    )
    next_attempt_at: Mapped[datetime] = MappedColumn[datetime](
        DateTime(timezone=True), server_default=func.now()
    )
    attempts: Mapped[int] = MappedColumn[int](server_default=text("0"))
    sent_at: Mapped[datetime | None] = MappedColumn[datetime | None](DateTime(timezone=True))
    last_error: Mapped[str | None] = MappedColumn[str | None](String(LAST_ERROR_LENGTH))

    __table_args__: tuple[Constraint | Index, ...] = (
        UniqueConstraint("dedupe_key"),
        CheckConstraint("attempts >= 0", name="attempts"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload"),
        Index("ix_notification_outbox_recipient_user_id", "recipient_user_id"),
        Index(
            "ix_notification_outbox_unsent",
            "next_attempt_at",
            postgresql_where=text("sent_at IS NULL"),
        ),
    )
