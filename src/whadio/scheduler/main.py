import asyncio
import logging
import signal

from ..notifications.settings import load_notification_settings
from ..retention.services import RetentionService
from ..retention.storage import RecordingStorage
from ..shared.database import Database, DatabaseSettings
from ..shared.storage import connect_s3_storage
from .composition import RetentionTransactions, notification_drainer
from .services import RetentionScheduler
from .settings import SchedulerSettings

logger = logging.getLogger(__name__)


async def run(*, once: bool = False) -> int:
    settings = SchedulerSettings.model_validate({})
    notification_settings = load_notification_settings()
    database = Database(DatabaseSettings.model_validate({}))
    try:
        retention = RetentionService(
            RetentionTransactions(database),
            RecordingStorage(connect_s3_storage(settings.storage)),
        )
        drainer = notification_drainer(notification_settings, database)
        if drainer is None:
            logger.info("No SMTP relay is configured; notifications are kept unsent")
        scheduler = RetentionScheduler(
            retention, settings.retention_interval_seconds, notifications=drainer
        )
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
