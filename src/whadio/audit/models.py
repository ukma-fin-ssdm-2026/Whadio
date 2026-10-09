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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, MappedColumn

from ..shared.database import Base


class AuditEvent(Base):
    __tablename__: str = "audit_event"

    audit_event_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    occurred_at: Mapped[datetime] = MappedColumn[datetime](DateTime(timezone=True))
    actor_user_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("user.user_id", ondelete="RESTRICT")
    )
    action: Mapped[str] = MappedColumn[str](Text)
    workspace_id: Mapped[UUID | None] = MappedColumn[UUID | None]()
    meeting_id: Mapped[UUID | None] = MappedColumn[UUID | None]()
    subject_id: Mapped[UUID | None] = MappedColumn[UUID | None]()
    details: Mapped[JsonValue | None] = MappedColumn[JsonValue | None](
        JSONB(none_as_null=True), nullable=True
    )

    __table_args__: tuple[Constraint | Index, ...] = (
        CheckConstraint(
            "action IN ('meeting_created', "
            "'meeting_renamed', "
            "'meeting_moved', "
            "'meeting_deleted', "
            "'meeting_evicted', "
            "'transcript_edited', "
            "'speaker_renamed', "
            "'notes_regenerated', "
            "'meeting_restricted', "
            "'meeting_unrestricted', "
            "'access_granted', "
            "'access_revoked', "
            "'share_created', "
            "'share_revoked', "
            "'share_access_approved', "
            "'share_access_declined', "
            "'member_invited', "
            "'invitation_cancelled', "
            "'member_joined', "
            "'member_removed', "
            "'member_role_changed', "
            "'workspace_deleted', "
            "'provider_configured', "
            "'mcp_key_created', "
            "'mcp_key_revoked')",
            name="action",
        ),
        Index("ix_audit_event_workspace_occurred", "workspace_id", "occurred_at"),
        Index("ix_audit_event_meeting_occurred", "meeting_id", "occurred_at"),
        Index("ix_audit_event_actor_occurred", "actor_user_id", "occurred_at"),
        CheckConstraint(
            "(workspace_id IS NULL) = (action IN ('mcp_key_created', 'mcp_key_revoked'))",
            name="workspace_scope",
        ),
    )
