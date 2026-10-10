from datetime import datetime
from typing import final
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, MappedColumn

from ..core.db import Base, UtcDateTime
from .schemas import Preset, Role, SessionKind, UserRead


@final
class User(Base):
    __tablename__ = "users"

    user_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    # Stored lowercased: addresses are compared case-insensitively everywhere.
    email: Mapped[str] = MappedColumn[str](String(254), unique=True)
    name: Mapped[str] = MappedColumn[str](String(100))
    password_hash: Mapped[str] = MappedColumn[str](String(64))
    is_administrator: Mapped[bool] = MappedColumn[bool](default=False)
    terms_accepted_at: Mapped[datetime] = MappedColumn[datetime](UtcDateTime)
    created_at: Mapped[datetime] = MappedColumn[datetime](UtcDateTime)

    def to_read(self) -> UserRead:
        return UserRead(
            id=self.user_id,
            email=self.email,
            name=self.name,
            is_administrator=self.is_administrator,
            created_at=self.created_at,
        )


@final
class UserSession(Base):
    __tablename__ = "sessions"

    session_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = MappedColumn[UUID](ForeignKey("users.user_id", ondelete="CASCADE"))
    kind: Mapped[SessionKind] = MappedColumn[SessionKind]()
    token_hash: Mapped[str] = MappedColumn[str](String(64), unique=True)
    created_at: Mapped[datetime] = MappedColumn[datetime](UtcDateTime)
    expires_at: Mapped[datetime] = MappedColumn[datetime](UtcDateTime)


@final
class Workspace(Base):
    __tablename__ = "workspaces"

    workspace_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    name: Mapped[str] = MappedColumn[str](String(100))
    default_preset: Mapped[Preset] = MappedColumn[Preset]("default_template")
    is_personal: Mapped[bool] = MappedColumn[bool]()
    created_at: Mapped[datetime] = MappedColumn[datetime](UtcDateTime)


@final
class WorkspaceMembership(Base):
    __tablename__ = "workspace_memberships"
    __table_args__: tuple[UniqueConstraint] = (UniqueConstraint("workspace_id", "user_id"),)

    workspace_membership_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = MappedColumn[UUID](ForeignKey("workspaces.workspace_id"))
    user_id: Mapped[UUID] = MappedColumn[UUID](ForeignKey("users.user_id"))
    role: Mapped[Role] = MappedColumn[Role]()
    joined_at: Mapped[datetime] = MappedColumn[datetime](UtcDateTime)
