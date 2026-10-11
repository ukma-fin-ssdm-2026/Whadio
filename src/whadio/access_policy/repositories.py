from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import Select, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..shared.pagination import ListWindow
from .models import ExternalShare, MeetingAccessGrant, ShareAccessRequest


class IAccessRepository(Protocol):
    async def recipient_shares(self, user_id: UUID, page: ListWindow) -> list[ExternalShare]: ...

    async def shares(
        self, meeting_id: UUID, page: ListWindow | None = None
    ) -> list[ExternalShare]: ...

    async def requests(
        self, share_id: UUID, page: ListWindow | None = None
    ) -> list[ShareAccessRequest]: ...

    def granted_meetings(self, user_id: UUID) -> Select[UUID]: ...

    async def grants(self, meeting_id: UUID) -> set[UUID]: ...

    async def replace_grants(self, meeting_id: UUID, grants: list[MeetingAccessGrant]) -> None: ...

    async def share(self, share_id: UUID, *, lock: bool = False) -> ExternalShare | None: ...

    async def request(self, request_id: UUID) -> ShareAccessRequest | None: ...

    async def requested(self, share_id: UUID, user_id: UUID) -> bool: ...

    async def save_share(self, share: ExternalShare) -> None: ...

    async def save_request(self, request: ShareAccessRequest) -> None: ...


class AccessRepository:
    async def shares(self, meeting_id: UUID, page: ListWindow | None = None) -> list[ExternalShare]:
        statement = select(ExternalShare).where(ExternalShare.meeting_id == meeting_id)
        if page is not None:
            if page.after is not None:
                timestamp = datetime.fromisoformat(page.after.key)
                statement = statement.where(
                    (ExternalShare.created_at < timestamp)
                    | (
                        (ExternalShare.created_at == timestamp)
                        & (ExternalShare.share_id < page.after.item_id)
                    )
                )
            statement = statement.limit(page.limit)
        return list(
            await self._session.scalars(
                statement.order_by(ExternalShare.created_at.desc(), ExternalShare.share_id.desc())
            )
        )

    async def recipient_shares(self, user_id: UUID, page: ListWindow) -> list[ExternalShare]:
        statement = select(ExternalShare).where(
            ExternalShare.recipient_user_id == user_id, ExternalShare.revoked_at.is_(None)
        )
        if page.after is not None:
            timestamp = datetime.fromisoformat(page.after.key)
            statement = statement.where(
                (ExternalShare.created_at < timestamp)
                | (
                    (ExternalShare.created_at == timestamp)
                    & (ExternalShare.share_id < page.after.item_id)
                )
            )
        return list(
            await self._session.scalars(
                statement.order_by(
                    ExternalShare.created_at.desc(), ExternalShare.share_id.desc()
                ).limit(page.limit)
            )
        )

    async def requests(
        self, share_id: UUID, page: ListWindow | None = None
    ) -> list[ShareAccessRequest]:
        statement = select(ShareAccessRequest).where(ShareAccessRequest.share_id == share_id)
        if page is not None:
            if page.after is not None:
                timestamp = datetime.fromisoformat(page.after.key)
                statement = statement.where(
                    (ShareAccessRequest.requested_at < timestamp)
                    | (
                        (ShareAccessRequest.requested_at == timestamp)
                        & (ShareAccessRequest.share_access_request_id < page.after.item_id)
                    )
                )
            statement = statement.limit(page.limit)
        return list(
            await self._session.scalars(
                statement.order_by(
                    ShareAccessRequest.requested_at.desc(),
                    ShareAccessRequest.share_access_request_id.desc(),
                )
            )
        )

    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    def granted_meetings(self, user_id: UUID) -> Select[UUID]:
        return select(MeetingAccessGrant.meeting_id).where(MeetingAccessGrant.user_id == user_id)

    async def grants(self, meeting_id: UUID) -> set[UUID]:
        return set(
            await self._session.scalars(
                select(MeetingAccessGrant.user_id).where(
                    MeetingAccessGrant.meeting_id == meeting_id
                )
            )
        )

    async def replace_grants(self, meeting_id: UUID, grants: list[MeetingAccessGrant]) -> None:
        await self._session.execute(
            delete(MeetingAccessGrant).where(MeetingAccessGrant.meeting_id == meeting_id)
        )
        self._session.add_all(grants)
        await self._session.flush()

    async def share(self, share_id: UUID, *, lock: bool = False) -> ExternalShare | None:
        statement = select(ExternalShare).where(ExternalShare.share_id == share_id)
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return await self._session.scalar(statement)

    async def request(self, request_id: UUID) -> ShareAccessRequest | None:
        return await self._session.get(ShareAccessRequest, request_id, populate_existing=True)

    async def requested(self, share_id: UUID, user_id: UUID) -> bool:
        return (
            await self._session.scalar(
                select(ShareAccessRequest.share_access_request_id).where(
                    ShareAccessRequest.share_id == share_id,
                    ShareAccessRequest.requester_user_id == user_id,
                )
            )
            is not None
        )

    async def save_share(self, share: ExternalShare) -> None:
        self._session.add(share)
        await self._session.flush()

    async def save_request(self, request: ShareAccessRequest) -> None:
        self._session.add(request)
        await self._session.flush()
