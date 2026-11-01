from datetime import UTC, datetime
from typing import Annotated, ClassVar
from uuid import UUID

from fastapi import APIRouter, Path, Response
from pydantic import ConfigDict, Field, SecretStr

from ...accounts.models import Invitation, WorkspaceMembership
from ...accounts.services import RegistrationDetails, RegistrationValidationError
from ..composition import Redemptions
from ..core.errors import ApiError, ErrorCode, ErrorDetail, error_responses
from ..core.schemas import Input, Output
from .auth import BrowserUser, set_session_cookie, user_read
from .schemas import (
    InvitationRead,
    InvitationState,
    InvitedRole,
    RegistrationComplete,
    Role,
    UserRead,
)

router = APIRouter(prefix="/invitations/{invitation_id}", tags=["workspaces"])
InvitationId = Annotated[UUID, Path(description="Invitation identifier from the link")]


class LinkToken(Input):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", str_strip_whitespace=False)
    token: SecretStr = Field(description="Secret from the invitation link fragment")


class PreviewRead(Output):
    workspace_id: UUID = Field(description="Workspace being joined")
    workspace_name: str = Field(description="Workspace display name")
    email: str = Field(description="Invited email address")
    role: InvitedRole = Field(description="Offered workspace role")
    account_exists: bool = Field(description="Whether to sign in instead of registering")


class MembershipRead(Output):
    user_id: UUID = Field(description="Member account identifier")
    workspace_id: UUID = Field(description="Workspace identifier")
    role: Role = Field(description="Granted workspace role")
    joined_at: datetime = Field(description="When the membership began")


class RegisteredRead(Output):
    user: UserRead = Field(description="Newly registered account")
    membership: MembershipRead = Field(description="Membership created through the invitation")


def _member(member: WorkspaceMembership) -> MembershipRead:
    return MembershipRead(
        user_id=member.user_id,
        workspace_id=member.workspace_id,
        role=Role(member.role.value.lower()),
        joined_at=member.joined_at,
    )


def _invitation(invitation: Invitation) -> InvitationRead:
    return InvitationRead(
        id=invitation.invitation_id,
        email=invitation.invited_email,
        role=InvitedRole(invitation.role.value.lower()),
        status=InvitationState(invitation.status.value),
        created_at=invitation.created_at,
        expires_at=invitation.expires_at,
        link_active=False,
    )


_ERRORS = error_responses(
    {
        400: "Malformed JSON",
        404: "LINK_INVALID: invalid or expired link",
        422: "VALIDATION_ERROR: invalid fields",
    }
)


@router.post("/preview", openapi_extra={"security": []}, responses=_ERRORS)
async def preview(
    invitation_id: InvitationId, payload: LinkToken, service: Redemptions, response: Response
) -> PreviewRead:
    found = await service.preview(
        invitation_id, payload.token.get_secret_value(), datetime.now(UTC)
    )
    response.headers["Cache-Control"] = "no-store"
    return PreviewRead(
        workspace_id=found.invitation.workspace_id,
        workspace_name=found.workspace_name,
        email=found.invitation.invited_email,
        role=InvitedRole(found.invitation.role.value.lower()),
        account_exists=found.account_exists,
    )


@router.post(
    "/accept",
    responses={
        **_ERRORS,
        **error_responses(
            {
                401: "Browser session required",
                403: "EMAIL_MISMATCH: sign in with the invited address",
                409: "ALREADY_MEMBER",
            }
        ),
    },
)
async def accept(
    invitation_id: InvitationId,
    payload: LinkToken,
    user: BrowserUser,
    service: Redemptions,
    response: Response,
) -> MembershipRead:
    member = await service.accept(
        invitation_id, payload.token.get_secret_value(), user.id, user.email, datetime.now(UTC)
    )
    response.headers["Cache-Control"] = "no-store"
    return _member(member)


@router.post("/decline", openapi_extra={"security": []}, responses=_ERRORS)
async def decline(
    invitation_id: InvitationId, payload: LinkToken, service: Redemptions, response: Response
) -> InvitationRead:
    invitation = await service.decline(
        invitation_id, payload.token.get_secret_value(), datetime.now(UTC)
    )
    response.headers["Cache-Control"] = "no-store"
    return _invitation(invitation)


@router.post(
    "/register",
    status_code=201,
    openapi_extra={"security": []},
    responses={**_ERRORS, **error_responses({409: "ACCOUNT_EXISTS: sign in and accept"})},
)
async def register(
    invitation_id: InvitationId,
    payload: RegistrationComplete,
    service: Redemptions,
    response: Response,
) -> RegisteredRead:
    try:
        signed, member = await service.register(
            invitation_id,
            payload.token.get_secret_value(),
            RegistrationDetails(
                payload.name, payload.password.get_secret_value(), payload.accept_terms
            ),
            datetime.now(UTC),
        )
    except RegistrationValidationError as error:
        raise ApiError(
            422,
            ErrorCode.VALIDATION_ERROR,
            "Request contains invalid fields",
            [ErrorDetail(field=error.field_name, message=str(error))],
        ) from None
    set_session_cookie(response, signed.token, signed.expires_at)
    response.headers["Cache-Control"] = "no-store"
    return RegisteredRead(user=user_read(signed.user), membership=_member(member))
