import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta

from ...contracts.common import JobMessage
from .jobs import IResultMessage, RunFailure, WorkerSpec

logger = logging.getLogger(__name__)


class InlineRunner[J: JobMessage, R: IResultMessage]:
    def __init__(
        self,
        spec: WorkerSpec[J, R],
        handler: Callable[[J], Awaitable[R]],
        *,
        timeout: timedelta,
    ) -> None:
        self._spec: WorkerSpec[J, R] = spec
        self._handler: Callable[[J], Awaitable[R]] = handler
        self._timeout: timedelta = timeout

    async def start(self) -> None:
        pass

    async def run(self, job: J) -> R:
        try:
            async with asyncio.timeout(self._timeout.total_seconds()):
                return await self._handler(job)
        except TimeoutError:
            return self._spec.failure_result(job, RunFailure.TIMED_OUT)
        except Exception:
            logger.exception("Job %s failed unexpectedly", job.job_id)
            return self._spec.failure_result(job, RunFailure.ERRORED)

    async def stop(self) -> None:
        pass
