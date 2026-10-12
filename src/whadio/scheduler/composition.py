from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from ..access_policy.repositories import AccessRepository
from ..access_policy.services import AccessPolicy
from ..accounts.repositories import MembershipRepository
from ..accounts.services import WorkspaceMembershipService
from ..meetings.retention import IRetentionMeetings, IRetentionNotifier, RetentionMeetings
from ..shared.database import Database


class RetentionTransactions:
    def __init__(
        self, database: Database, notifications: Callable[[AsyncSession], IRetentionNotifier]
    ) -> None:
        self._database: Database = database
        self._notifications: Callable[[AsyncSession], IRetentionNotifier] = notifications

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[IRetentionMeetings]:
        async with self._database.transaction() as session:
            yield RetentionMeetings(
                session,
                AccessPolicy(
                    AccessRepository(session),
                    WorkspaceMembershipService(MembershipRepository(session)),
                ),
                self._notifications(session),
            )
