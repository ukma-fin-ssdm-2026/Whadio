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
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, MappedColumn

from ..shared.database import Base, enum_values
from .enums import (
    InvitationRole,
    InvitationStatus,
    LlmProvider,
    NotesTemplate,
    SessionKind,
    WorkspaceRole,
)


class User(Base):
    __tablename__: str = "user"

    user_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    email: Mapped[str] = MappedColumn[str](Text)
    name: Mapped[str] = MappedColumn[str](Text)
    password_hash: Mapped[str] = MappedColumn[str](Text)
    is_administrator: Mapped[bool] = MappedColumn[bool](server_default=false())
    terms_accepted_at: Mapped[datetime] = MappedColumn[datetime](DateTime(timezone=True))
    created_at: Mapped[datetime] = MappedColumn[datetime](
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__: tuple[Constraint | Index, ...] = (
        Index("uq_user_email", func.lower(email), unique=True),
    )


class Workspace(Base):
    __tablename__: str = "workspace"

    workspace_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    name: Mapped[str] = MappedColumn[str](Text)
    default_template: Mapped[NotesTemplate] = MappedColumn[NotesTemplate](
        Enum(
            NotesTemplate,
            name="template",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            validate_strings=True,
        ),
    )
    created_at: Mapped[datetime] = MappedColumn[datetime](
        DateTime(timezone=True), server_default=func.now()
    )
    is_personal: Mapped[bool] = MappedColumn[bool](server_default=false())


class WorkspaceMembership(Base):
    __tablename__: str = "workspace_membership"

    workspace_membership_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("workspace.workspace_id", ondelete="CASCADE")
    )
    user_id: Mapped[UUID] = MappedColumn[UUID](ForeignKey("user.user_id", ondelete="RESTRICT"))
    role: Mapped[WorkspaceRole] = MappedColumn[WorkspaceRole](
        Enum(
            WorkspaceRole,
            name="role",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            validate_strings=True,
        ),
    )
    joined_at: Mapped[datetime] = MappedColumn[datetime](
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__: tuple[Constraint | Index, ...] = (
        UniqueConstraint("workspace_id", "user_id"),
        Index(
            "uq_workspace_owner",
            "workspace_id",
            unique=True,
            postgresql_where=text("role = 'Owner'"),
        ),
        Index("ix_workspace_membership_user_id", "user_id"),
    )


class Invitation(Base):
    __tablename__: str = "invitation"

    invitation_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("workspace.workspace_id", ondelete="CASCADE")
    )
    invited_email: Mapped[str] = MappedColumn[str](Text)
    role: Mapped[InvitationRole] = MappedColumn[InvitationRole](
        Enum(
            InvitationRole,
            name="role",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            validate_strings=True,
        ),
    )
    invited_by_user_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("user.user_id", ondelete="RESTRICT")
    )
    status: Mapped[InvitationStatus] = MappedColumn[InvitationStatus](
        Enum(
            InvitationStatus,
            name="status",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            validate_strings=True,
        ),
    )
    token_hash: Mapped[str] = MappedColumn[str](Text)
    created_at: Mapped[datetime] = MappedColumn[datetime](
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = MappedColumn[datetime](DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = MappedColumn[datetime | None](DateTime(timezone=True))

    __table_args__: tuple[Constraint | Index, ...] = (
        CheckConstraint("expires_at > created_at", name="expiry"),
        UniqueConstraint("token_hash"),
        Index(
            "uq_invitation_pending",
            workspace_id,
            func.lower(invited_email),
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_invitation_expires_at", "expires_at"),
        Index("ix_invitation_inviter_created", "invited_by_user_id", "created_at"),
        Index(
            "ix_invitation_workspace_email_created",
            workspace_id,
            func.lower(invited_email),
            created_at,
        ),
    )


class PendingRegistration(Base):
    __tablename__: str = "pending_registration"

    pending_registration_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    email: Mapped[str] = MappedColumn[str](Text)
    token_hash: Mapped[str] = MappedColumn[str](Text)
    created_at: Mapped[datetime] = MappedColumn[datetime](
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = MappedColumn[datetime](DateTime(timezone=True))

    __table_args__: tuple[Constraint | Index, ...] = (
        Index("uq_pending_registration_email", func.lower(email), unique=True),
        UniqueConstraint("token_hash"),
        CheckConstraint("expires_at > created_at", name="expiry"),
        Index("ix_pending_registration_expires_at", "expires_at"),
    )


class PasswordReset(Base):
    __tablename__: str = "password_reset"

    password_reset_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = MappedColumn[UUID](ForeignKey("user.user_id", ondelete="CASCADE"))
    token_hash: Mapped[str] = MappedColumn[str](Text)
    created_at: Mapped[datetime] = MappedColumn[datetime](
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = MappedColumn[datetime](DateTime(timezone=True))

    __table_args__: tuple[Constraint | Index, ...] = (
        UniqueConstraint("user_id"),
        UniqueConstraint("token_hash"),
        CheckConstraint("expires_at > created_at", name="expiry"),
        Index("ix_password_reset_expires_at", "expires_at"),
    )


class Session(Base):
    __tablename__: str = "session"

    session_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = MappedColumn[UUID](ForeignKey("user.user_id", ondelete="CASCADE"))
    kind: Mapped[SessionKind] = MappedColumn[SessionKind](
        Enum(
            SessionKind,
            name="kind",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            validate_strings=True,
        ),
    )
    token_hash: Mapped[str] = MappedColumn[str](Text)
    created_at: Mapped[datetime] = MappedColumn[datetime](
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = MappedColumn[datetime](DateTime(timezone=True))

    __table_args__: tuple[Constraint | Index, ...] = (
        UniqueConstraint("token_hash"),
        CheckConstraint("expires_at > created_at", name="expiry"),
        Index("ix_session_user_id", "user_id"),
        Index("ix_session_expires_at", "expires_at"),
    )


class LlmProviderConfig(Base):
    __tablename__: str = "llm_provider_config"

    provider_config_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = MappedColumn[UUID](
        ForeignKey("workspace.workspace_id", ondelete="CASCADE")
    )
    is_enabled: Mapped[bool] = MappedColumn[bool]()
    provider: Mapped[LlmProvider] = MappedColumn[LlmProvider](
        Enum(
            LlmProvider,
            name="provider",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            validate_strings=True,
        ),
    )
    api_key_encrypted: Mapped[str | None] = MappedColumn[str | None](Text)
    created_at: Mapped[datetime] = MappedColumn[datetime](
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__: tuple[Constraint | Index, ...] = (
        UniqueConstraint("workspace_id"),
        CheckConstraint(
            "provider = 'Whadio' OR api_key_encrypted IS NOT NULL", name="encrypted_key"
        ),
    )


class McpKey(Base):
    __tablename__: str = "mcp_key"

    mcp_key_id: Mapped[UUID] = MappedColumn[UUID](primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = MappedColumn[UUID](ForeignKey("user.user_id", ondelete="CASCADE"))
    key_hash: Mapped[str] = MappedColumn[str](Text)
    created_at: Mapped[datetime] = MappedColumn[datetime](
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = MappedColumn[datetime | None](DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = MappedColumn[datetime | None](DateTime(timezone=True))

    __table_args__: tuple[Constraint | Index, ...] = (
        UniqueConstraint("key_hash"),
        CheckConstraint("expires_at IS NULL OR expires_at > created_at", name="expiry"),
        Index("ix_mcp_key_user_id", "user_id"),
    )
