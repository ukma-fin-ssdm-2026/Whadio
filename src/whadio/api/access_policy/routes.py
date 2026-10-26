from datetime import UTC, datetime
from typing import Annotated, Self
from uuid import UUID

from fastapi import APIRouter, Path, Query, Request, Response
from pydantic import Field, model_validator

from ...access_policy.models import ExternalShare, ShareAccessRequest
from ...access_policy.services import ContentPath
from ...shared.errors import Failure, UseCaseError
from ...shared.pagination import ListCursor
from ..accounts.auth import BrowserUser
from ..composition import Access, Meetings
from ..core.errors import ApiError, ErrorCode, error_responses
from ..core.pagination import list_page, list_window
from ..core.schemas import Input, Output, Page, PageQuery
from ..meetings.schemas import AccessMode, MeetingId, NoteRead, TranscriptRead
from ..meetings.views import notes_read, transcript_read

ShareId = Annotated[UUID, Path(description="External share identifier")]
RequestId = Annotated[UUID, Path(description="Share access request identifier")]

router = APIRouter(
    tags=["access"],
    responses=error_responses(
        {
            401: "Authentication required",
            403: "Insufficient role",
            404: "Not found or not visible",
            409: "Access or share conflict",
            410: "Recipient access was revoked",
            422: "Invalid input",
            503: "Notifications integration unavailable",
        }
    ),
)


class AccessInput(Input):
    access_mode: AccessMode = Field(description="Workspace or selected-member access")
    member_ids: list[UUID] = Field(default_factory=list, description="Selected workspace members")

    @model_validator(mode="after")
    def validate_members(self) -> Self:
        if (self.access_mode == AccessMode.RESTRICTED) != bool(self.member_ids):
            raise ValueError("Restricted access needs members; workspace access takes none")
        if len(set(self.member_ids)) != len(self.member_ids):
            raise ValueError("A member may appear once")
        return self


class AccessRead(Output):
    access_mode: AccessMode = Field(description="Meeting visibility")
    member_ids: list[UUID] = Field(description="Selected members")


@router.get(
    "/meetings/{meeting_id}/access",
    description="Read the access mode and selected members of a meeting the caller can read.",
)
async def read_access(meeting_id: MeetingId, user: BrowserUser, service: Access) -> AccessRead:
    restricted, members = await service.read_access(user.id, meeting_id)
    return AccessRead(
        access_mode=AccessMode.RESTRICTED if restricted else AccessMode.WORKSPACE,
        member_ids=sorted(members),
    )


@router.put(
    "/meetings/{meeting_id}/access",
    description=(
        "Replace meeting access as a Moderator or Owner who can read it. "
        "Restricted access requires selected workspace members; unselected "
        "members lose access immediately."
    ),
)
async def replace_access(
    meeting_id: MeetingId, payload: AccessInput, user: BrowserUser, service: Access
) -> AccessRead:
    await service.replace_access(
        user.id,
        meeting_id,
        set(payload.member_ids),
        datetime.now(UTC),
        restricted=payload.access_mode == AccessMode.RESTRICTED,
    )
    return AccessRead(access_mode=payload.access_mode, member_ids=payload.member_ids)


class ShareInput(Input):
    redact_speaker_names: bool = Field(
        default=False, strict=True, description="Replace speaker names"
    )


class ShareRead(Output):
    id: UUID = Field(description="Share identifier")
    redact_speaker_names: bool = Field(description="Whether speaker names are hidden")
    recipient_user_id: UUID | None = Field(description="Approved recipient")
    revoked_at: datetime | None = Field(description="When access ended")


class ShareCreated(ShareRead):
    link: str = Field(description="Share link with one-time token disclosure in its fragment")


def _share_read(share: ExternalShare) -> ShareRead:
    return ShareRead(
        id=share.share_id,
        redact_speaker_names=share.redact_speaker_names,
        recipient_user_id=share.recipient_user_id,
        revoked_at=share.revoked_at,
    )


@router.get(
    "/meetings/{meeting_id}/shares",
    description="List shares of a meeting the caller can read, newest first.",
)
async def list_shares(
    meeting_id: MeetingId, query: Annotated[PageQuery, Query()], user: BrowserUser, service: Access
) -> Page[ShareRead]:
    scope = f"meeting-shares:{meeting_id}:{user.id}"
    shares = await service.shares(
        user.id, meeting_id, list_window(query, scope, chronological=True)
    )
    last = shares[min(len(shares), query.limit) - 1] if shares else None
    cursor = None if last is None else ListCursor(last.created_at.isoformat(), last.share_id)
    return list_page([_share_read(item) for item in shares], query, scope, cursor)


@router.get(
    "/users/me/shares",
    description="List active shares bound to the signed-in account, newest first.",
)
async def recipient_shares(
    query: Annotated[PageQuery, Query()], user: BrowserUser, service: Access
) -> Page[ShareRead]:
    scope = f"recipient-shares:{user.id}"
    shares = await service.recipient_shares(user.id, list_window(query, scope, chronological=True))
    last = shares[min(len(shares), query.limit) - 1] if shares else None
    cursor = None if last is None else ListCursor(last.created_at.isoformat(), last.share_id)
    return list_page([_share_read(item) for item in shares], query, scope, cursor)


@router.post(
    "/meetings/{meeting_id}/shares",
    status_code=201,
    description=(
        "Create a read-only share of an accessible meeting. Disclose its token "
        "once in the link fragment; a share creator must approve the recipient "
        "account."
    ),
)
async def create_share(
    meeting_id: MeetingId,
    payload: ShareInput,
    user: BrowserUser,
    service: Access,
    request: Request,
    response: Response,
) -> ShareCreated:
    created = await service.create_share(
        user.id, meeting_id, datetime.now(UTC), redact=payload.redact_speaker_names
    )
    share = created.share
    response.headers["Location"] = f"/api/v1/shares/{share.share_id}"
    return ShareCreated(
        id=share.share_id,
        redact_speaker_names=share.redact_speaker_names,
        recipient_user_id=share.recipient_user_id,
        revoked_at=share.revoked_at,
        link=f"{request.base_url}shares/{share.share_id}#token={created.token}",
    )


@router.delete(
    "/shares/{share_id}",
    status_code=204,
    description=(
        "Revoke a share as its creator. Its bound recipient can no longer read "
        "the meeting through it."
    ),
)
async def revoke_share(share_id: ShareId, user: BrowserUser, service: Access) -> None:
    await service.revoke(user.id, share_id, datetime.now(UTC))


class RequestInput(Input):
    token: str = Field(min_length=1, max_length=256, description="Token from the link fragment")


class RequestRead(Output):
    id: UUID = Field(description="Access request identifier")
    requester_user_id: UUID = Field(description="Requesting account")
    name: str = Field(description="Requester's name, shown only to them and the share creator")
    email: str = Field(description="Requester's email, shown only to them and the share creator")
    status: str = Field(description="pending, approved or declined")


async def _request_read(
    request: ShareAccessRequest, actor_id: UUID, service: Access
) -> RequestRead:
    profile = await service.requester_profile(actor_id, request.share_access_request_id)
    return RequestRead(
        id=request.share_access_request_id,
        requester_user_id=request.requester_user_id,
        name=profile.name,
        email=profile.email,
        status=request.status,
    )


@router.post(
    "/shares/{share_id}/access-requests",
    status_code=201,
    description=(
        "Request access with a token from the share link fragment. Requires an "
        "existing account and reserves the creator notification in the same "
        "transaction."
    ),
)
async def request_access(
    share_id: ShareId, payload: RequestInput, user: BrowserUser, service: Access, response: Response
) -> RequestRead:
    requested = await service.request_access(user.id, share_id, payload.token, datetime.now(UTC))
    response.headers["Location"] = (
        f"/api/v1/share-access-requests/{requested.share_access_request_id}"
    )
    return await _request_read(requested, user.id, service)


@router.get(
    "/shares/{share_id}/access-requests",
    description="List access requests for a share as its creator, newest first.",
)
async def list_requests(
    share_id: ShareId, query: Annotated[PageQuery, Query()], user: BrowserUser, service: Access
) -> Page[RequestRead]:
    scope = f"share-requests:{share_id}:{user.id}"
    requests = await service.requests(
        user.id, share_id, list_window(query, scope, chronological=True)
    )
    last = requests[min(len(requests), query.limit) - 1] if requests else None
    cursor = (
        None
        if last is None
        else ListCursor(last.requested_at.isoformat(), last.share_access_request_id)
    )
    return list_page(
        [await _request_read(item, user.id, service) for item in requests], query, scope, cursor
    )


@router.post(
    "/share-access-requests/{request_id}/approve",
    description=(
        "Approve a pending request as the share creator, binding the share to "
        "that one account. Refuses revoked or already bound shares."
    ),
)
async def approve_request(request_id: RequestId, user: BrowserUser, service: Access) -> RequestRead:
    return await _request_read(
        await service.decide(user.id, request_id, datetime.now(UTC), approve=True), user.id, service
    )


@router.post(
    "/share-access-requests/{request_id}/decline",
    description="Decline a pending access request as the share creator.",
)
async def decline_request(request_id: RequestId, user: BrowserUser, service: Access) -> RequestRead:
    return await _request_read(
        await service.decide(user.id, request_id, datetime.now(UTC), approve=False),
        user.id,
        service,
    )


async def _shared_meeting(share_id: ShareId, user_id: UUID, access: Access) -> UUID:
    try:
        permission = await access.policy.authorize_share(share_id, user_id, ContentPath.READ)
    except UseCaseError as error:
        if error.code == Failure.SHARE_REVOKED:
            raise ApiError(410, ErrorCode.SHARE_REVOKED, "Share revoked") from None
        raise
    if permission.meeting_id is None:
        raise UseCaseError(Failure.NOT_FOUND)
    return permission.meeting_id


@router.get(
    "/shares/{share_id}/transcript",
    description=(
        "Read a transcript through an active share bound to the caller, "
        "applying speaker-name redaction where configured. Export and onward "
        "sharing are not permitted."
    ),
)
async def shared_transcript(
    share_id: ShareId,
    user: BrowserUser,
    access: Access,
    meetings: Meetings,
    revision_id: Annotated[
        UUID | None, Query(description="Revision to read; current when omitted")
    ] = None,
) -> TranscriptRead:
    meeting_id = await _shared_meeting(share_id, user.id, access)
    return transcript_read(
        await meetings.shared_transcript(user.id, share_id, meeting_id, revision_id)
    )


@router.get(
    "/shares/{share_id}/notes",
    description=(
        "List notes through an active share bound to the caller, applying "
        "configured speaker-name redaction."
    ),
)
async def shared_notes(
    share_id: ShareId,
    query: Annotated[PageQuery, Query()],
    user: BrowserUser,
    access: Access,
    meetings: Meetings,
) -> Page[NoteRead]:
    meeting_id = await _shared_meeting(share_id, user.id, access)
    scope = f"shared-notes:{share_id}:{user.id}"
    versions = await meetings.shared_notes(
        user.id, share_id, meeting_id, list_window(query, scope, chronological=True)
    )
    last = versions[min(len(versions), query.limit) - 1].note if versions else None
    cursor = None if last is None else ListCursor(last.created_at.isoformat(), last.note_id)
    return list_page(notes_read(versions), query, scope, cursor)
