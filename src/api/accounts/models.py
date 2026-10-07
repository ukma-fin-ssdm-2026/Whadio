from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, UtcDateTime
from .schemas import Preset, Role, SessionKind, UserRead


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # Stored lowercased: addresses are compared case-insensitively everywhere.
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(64))
    is_administrator: Mapped[bool] = mapped_column(default=False)
    terms_accepted_at: Mapped[datetime] = mapped_column(UtcDateTime)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)

    def to_read(self) -> UserRead:
        return UserRead(
            id=self.user_id,
            email=self.email,
            name=self.name,
            is_administrator=self.is_administrator,
            created_at=self.created_at,
        )


class UserSession(Base):
    __tablename__ = "sessions"

    session_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"))
    kind: Mapped[SessionKind]
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)


class Workspace(Base):
    __tablename__ = "workspaces"

    workspace_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100))
    default_preset: Mapped[Preset] = mapped_column("default_template")
    is_personal: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class WorkspaceMembership(Base):
    __tablename__ = "workspace_memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)

    workspace_membership_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.workspace_id"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.user_id"))
    role: Mapped[Role]
    joined_at: Mapped[datetime] = mapped_column(UtcDateTime)
