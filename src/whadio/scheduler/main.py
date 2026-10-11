import asyncio
import logging
import signal
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ..meetings.retention import IRetentionNotifier, NotificationUnavailableError
from ..retention.services import RetentionService
from ..retention.storage import RecordingStorage
from ..shared.database import Database, DatabaseSettings
from ..shared.storage import connect_s3_storage
from .composition import RetentionTransactions
from .services import RetentionScheduler
from .settings import SchedulerSettings


class UnavailableRetentionNotifications:
    async def enqueue(self, meeting_id: UUID, recipient_id: UUID, deadline: datetime) -> None:
        del meeting_id, recipient_id, deadline
        raise NotificationUnavailableError("Recording warnings need a notification integration")


async def run(
    *,
    once: bool = False,
    notifications: Callable[[AsyncSession], IRetentionNotifier] | None = None,
) -> int:
    settings = SchedulerSettings.model_validate({})
    database = Database(DatabaseSettings.model_validate({}))
    try:
        retention = RetentionService(
            RetentionTransactions(
                database,
                notifications
                if notifications is not None
                else lambda _session: UnavailableRetentionNotifications(),
            ),
            RecordingStorage(connect_s3_storage(settings.storage)),
        )
        scheduler = RetentionScheduler(retention, settings.retention_interval_seconds)
        if once:
            return await scheduler.tick()
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, stop.set)
        try:
            await scheduler.serve(stop)
        finally:
            for signum in (signal.SIGINT, signal.SIGTERM):
                loop.remove_signal_handler(signum)
        return 0
    finally:
        await database.close()


def main(*, once: bool = False) -> int:
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(run(once=once))
