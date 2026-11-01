from datetime import datetime
from enum import StrEnum
from typing import Annotated, ClassVar, Self
from uuid import UUID

from fastapi import Path
from pydantic import ConfigDict, EmailStr, Field, SecretStr, StringConstraints, model_validator

from ...accounts.enums import RegistrationMode
from ..core.schemas import DisplayText, Input, Output

USER_ID_EXAMPLE = "3f6c1d2e-8a4b-4c5d-9e0f-1a2b3c4d5e6f"
WORKSPACE_ID_EXAMPLE = "7b1e9c40-2d3f-4a5b-8c6d-0e1f2a3b4c5d"


class Role(StrEnum):
    MEMBER = "member"
    MODERATOR = "moderator"
    OWNER = "owner"


class InvitedRole(StrEnum):
    MEMBER = "member"
    MODERATOR = "moderator"


class InvitationState(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"


class SessionKind(StrEnum):
    BROWSER = "browser"
    EXTENSION = "extension"


class Preset(StrEnum):
    SUMMARY = "summary"
    DETAILED = "detailed"
    INTERVIEW = "interview"


class Provider(StrEnum):
    WHADIO = "whadio"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"


WorkspaceId = Annotated[
    UUID, Path(description="Workspace identifier", examples=[WORKSPACE_ID_EXAMPLE])
]
WorkspaceName = Annotated[
    DisplayText,
    Field(min_length=1, max_length=100, description="Workspace name", examples=["Product team"]),
]


class SignIn(Input):
    email: EmailStr = Field(
        max_length=254, description="Account email address", examples=["alice@whadio.dev"]
    )
    password: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(
        min_length=1,
        max_length=128,
        description="Account password, compared exactly: surrounding spaces are part of it",
        examples=["whadio-demo-pass"],
    )
    kind: SessionKind = Field(
        default=SessionKind.BROWSER,
        description="`browser` sets the session cookie; `extension` returns a token for the "
        "Chrome extension instead",
    )


class UserRead(Output):
    id: UUID = Field(description="User identifier", examples=[USER_ID_EXAMPLE])
    email: str = Field(description="Proven email address", examples=["alice@whadio.dev"])
    name: str = Field(description="Display name", examples=["Alice Owner"])
    is_administrator: bool = Field(description="Whether the admin dashboard is available")
    created_at: datetime = Field(description="When the account was created")


class SessionRead(Output):
    kind: SessionKind = Field(description="Kind of session created")
    expires_at: datetime = Field(
        description="Fixed end of the session: 14 days for `browser`, 24 hours for "
        "`extension`; use never extends it"
    )
    user: UserRead
    token: str | None = Field(
        default=None,
        description="Bearer token, shown once, only for `extension` sessions; browser "
        "sessions get an HttpOnly cookie instead",
    )


class McpKeyCreate(Input):
    expires_in_days: int | None = Field(
        default=None,
        ge=1,
        le=365,
        strict=True,
        description="Days until expiry; omit for a key that does not expire",
    )


class McpKeyRead(Output):
    id: UUID = Field(description="MCP key identifier")
    created_at: datetime = Field(description="When the key was created")
    expires_at: datetime | None = Field(description="When the key expires, or null")
    revoked_at: datetime | None = Field(description="When the key was revoked, or null")
    is_active: bool = Field(description="Whether the key can authenticate now")


class McpKeyCreated(McpKeyRead):
    secret: str = Field(
        description="Bearer token shown only in this response; store it before closing"
    )


class WorkspaceCreate(Input):
    name: WorkspaceName
    default_preset: Preset = Field(
        default=Preset.SUMMARY, description="Notes preset used when none is chosen"
    )


class WorkspaceUpdate(Input):
    name: WorkspaceName | None = Field(default=None, description="New workspace name")
    default_preset: Preset | None = Field(
        default=None, description="Notes preset used when none is chosen"
    )

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if self.name is None and self.default_preset is None:
            raise ValueError("give at least one of `name` and `default_preset`")
        return self


class WorkspaceSummary(Output):
    id: UUID = Field(description="Workspace identifier", examples=[WORKSPACE_ID_EXAMPLE])
    name: str = Field(description="Workspace name", examples=["Product team"])
    is_personal: bool = Field(description="The account's own workspace, created with it")
    my_role: Role = Field(description="The caller's role here")
    member_count: int = Field(ge=1, description="Number of members", examples=[4])
    notes_provider: Provider = Field(
        description="Where transcripts go for notes; anything but `whadio` sends the "
        "transcripts in the context set to that provider"
    )
    created_at: datetime = Field(description="When the workspace was created")


class WorkspaceRead(WorkspaceSummary):
    default_preset: Preset = Field(description="Notes preset used when none is chosen")
    notes_model: str = Field(
        description="The model behind `notes_provider`", examples=["gemma4:12b-it-qat"]
    )


class InvitationCreate(Input):
    email: EmailStr = Field(
        max_length=254, description="Email address to invite", examples=["bob@whadio.dev"]
    )
    role: InvitedRole = Field(description="Workspace role granted when the invitation is accepted")


class InvitationRead(Output):
    id: UUID = Field(description="Invitation identifier")
    email: str = Field(description="Invited email address")
    role: InvitedRole = Field(description="Role offered by this invitation")
    status: InvitationState = Field(description="Current invitation state")
    created_at: datetime = Field(description="When this invitation was most recently issued")
    expires_at: datetime = Field(description="When this invitation becomes unusable")
    link_active: bool = Field(
        description="Whether the link can currently be accepted, including inviter authority"
    )


class InvitationCreated(InvitationRead):
    link: str | None = Field(
        description="One-time invitation link in invite-only mode; never returned by list"
    )


class RegistrationComplete(Input):
    # Per-field StringConstraints cannot preserve whitespace on SecretStr in both validation modes.
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", str_strip_whitespace=False)

    token: SecretStr = Field(description="Secret from the registration link fragment")
    name: DisplayText = Field(min_length=1, max_length=100, description="Account display name")
    password: SecretStr = Field(
        min_length=12,
        max_length=128,
        description="12 to 128 characters, a digit and an uppercase letter",
    )
    accept_terms: bool = Field(strict=True, description="Explicit acceptance of the instance Terms")


class InstanceRead(Output):
    registration_mode: RegistrationMode = Field(description="How this instance admits accounts")
    api_version: str = Field(description="Version of the Web API")


class PasswordResetComplete(Input):
    # Per-field StringConstraints cannot preserve whitespace on SecretStr in both validation modes.
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", str_strip_whitespace=False)

    token: SecretStr = Field(description="Secret from the password-reset link fragment")
    password: SecretStr = Field(
        min_length=12,
        max_length=128,
        description="12 to 128 characters, a digit and an uppercase letter",
    )
