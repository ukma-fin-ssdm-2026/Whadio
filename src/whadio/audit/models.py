from datetime import datetime
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import (
    CheckConstraint,
    Constraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, MappedColumn

from ..shared.database import Base, enum_values
from .enums import AuditAction


class AuditEvent(Base):
    __tablename__: str = "audit_event"

    audit_event_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    occurred_at: Mapped[datetime] = MappedColumn[datetime](
        DateTime(timezone=True), server_default=func.now()
    )
    actor_user_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("user.user_id", ondelete="RESTRICT")
    )
    action: Mapped[AuditAction] = MappedColumn[AuditAction](
        Enum(
            AuditAction,
            name="action",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            validate_strings=True,
        ),
    )
    workspace_id: Mapped[UUID | None] = MappedColumn[UUID | None]()
    meeting_id: Mapped[UUID | None] = MappedColumn[UUID | None]()
    subject_id: Mapped[UUID | None] = MappedColumn[UUID | None]()
    details: Mapped[JsonValue | None] = MappedColumn[JsonValue | None](
        JSONB(none_as_null=True), nullable=True
    )

    __table_args__: tuple[Constraint | Index, ...] = (
        Index("ix_audit_event_workspace_occurred", "workspace_id", "occurred_at"),
        Index("ix_audit_event_meeting_occurred", "meeting_id", "occurred_at"),
        Index("ix_audit_event_actor_occurred", "actor_user_id", "occurred_at"),
        CheckConstraint(
            "(workspace_id IS NULL) = (action IN ('mcp_key_created', 'mcp_key_revoked'))",
            name="workspace_scope",
        ),
    )
