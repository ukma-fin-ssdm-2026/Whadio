from datetime import UTC, datetime
from typing import Annotated, ClassVar
from uuid import UUID

from fastapi import APIRouter, Path, Response
from pydantic import ConfigDict, Field, SecretStr

from ...accounts.models import WorkspaceMembership
from ...accounts.services import RegistrationDetails, RegistrationValidationError
from ..composition import Redemptions
from ..core.errors import (
    DOC_INVALID,
    DOC_MALFORMED,
    DOC_UNAUTHENTICATED,
    ApiError,
    ErrorCode,
    ErrorDetail,
    error_responses,
)
from ..core.schemas import Input, Output
from .auth import BrowserUser, set_session_cookie, user_read
from .invitation_mapping import invitation_read
from .schemas import (
    InvitationRead,
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


_ERRORS = error_responses(
    {
        400: DOC_MALFORMED,
        404: "LINK_INVALID: invalid or expired link",
        422: DOC_INVALID,
    }
)


@router.post(
    "/preview",
    summary="Preview an invitation",
    response_description="The workspace, invited address, offered role and account existence",
    description="Validates the invitation token from the request body and returns the workspace, "
    "offered role and whether the invited address already has an account. No session is required.",
    openapi_extra={"security": []},
    responses=_ERRORS,
)
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
    summary="Accept an invitation",
    response_description="The granted workspace membership",
    description="Requires a browser session with the invited email address. Consumes the valid "
    "invitation and grants membership; repeating acceptance returns the existing membership.",
    responses={
        **_ERRORS,
        **error_responses(
            {
                401: DOC_UNAUTHENTICATED,
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


@router.post(
    "/decline",
    summary="Decline an invitation",
    response_description="The declined invitation",
    description="Validates the invitation token from the request body and marks the pending "
    "invitation declined. No session is required; the link cannot be used afterwards.",
    openapi_extra={"security": []},
    responses=_ERRORS,
)
async def decline(
    invitation_id: InvitationId, payload: LinkToken, service: Redemptions, response: Response
) -> InvitationRead:
    invitation = await service.decline(
        invitation_id, payload.token.get_secret_value(), datetime.now(UTC)
    )
    response.headers["Cache-Control"] = "no-store"
    return invitation_read(invitation, link_active=False)


@router.post(
    "/register",
    summary="Register through an invitation",
    response_description="The new user and granted workspace membership",
    status_code=201,
    description="Creates an account for the invited address, its personal workspace and default "
    "folder, and the invited membership atomically. Requires a valid invitation token, a strong "
    "password and Terms acceptance; consumes the link and sets the browser session cookie.",
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
