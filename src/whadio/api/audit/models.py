from datetime import datetime
from enum import StrEnum
from typing import final
from uuid import UUID, uuid4

from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, MappedColumn

from ..core.db import Base, UtcDateTime


class AuditAction(StrEnum):
    MEETING_CREATED = "meeting_created"
    MEETING_RENAMED = "meeting_renamed"
    MEETING_MOVED = "meeting_moved"
    MEETING_DELETED = "meeting_deleted"
    MEETING_EVICTED = "meeting_evicted"
    TRANSCRIPT_EDITED = "transcript_edited"
    SPEAKER_RENAMED = "speaker_renamed"
    NOTES_REGENERATED = "notes_regenerated"
    MEETING_RESTRICTED = "meeting_restricted"
    MEETING_UNRESTRICTED = "meeting_unrestricted"
    ACCESS_GRANTED = "access_granted"
    ACCESS_REVOKED = "access_revoked"
    SHARE_CREATED = "share_created"
    SHARE_REVOKED = "share_revoked"
    SHARE_ACCESS_APPROVED = "share_access_approved"
    SHARE_ACCESS_DECLINED = "share_access_declined"
    MEMBER_INVITED = "member_invited"
    INVITATION_CANCELLED = "invitation_cancelled"
    MEMBER_JOINED = "member_joined"
    MEMBER_REMOVED = "member_removed"
    MEMBER_ROLE_CHANGED = "member_role_changed"
    WORKSPACE_DELETED = "workspace_deleted"
    PROVIDER_CONFIGURED = "provider_configured"
    MCP_KEY_CREATED = "mcp_key_created"
    MCP_KEY_REVOKED = "mcp_key_revoked"


@final
class AuditEvent(Base):
    """Append-only (ADR-005): rows are only ever inserted, never updated or deleted.

    `workspace_id` and `meeting_id` have no foreign keys, so events outlive what they refer to.
    """

    __tablename__ = "audit_events"

    audit_event_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    occurred_at: Mapped[datetime] = MappedColumn[datetime](UtcDateTime)
    actor_user_id: Mapped[UUID] = MappedColumn[UUID]()
    action: Mapped[AuditAction] = MappedColumn[AuditAction]()
    workspace_id: Mapped[UUID | None] = MappedColumn[UUID | None]()
    meeting_id: Mapped[UUID | None] = MappedColumn[UUID | None]()
    subject_id: Mapped[UUID | None] = MappedColumn[UUID | None]()
    details: Mapped[dict[str, str] | None] = MappedColumn[dict[str, str] | None](JSON)
