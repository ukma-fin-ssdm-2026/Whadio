import asyncio
import logging
import multiprocessing
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from multiprocessing.connection import Connection
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter

from ...contracts.common import JobMessage
from .jobs import IResultMessage, RunFailure, WorkerSpec

if TYPE_CHECKING:
    from multiprocessing.context import SpawnProcess

logger = logging.getLogger(__name__)

_READY: Final = b"ready"
_STOP_GRACE_SECONDS: Final = 10.0


class SlotStartupError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class SlotProgram[J: JobMessage, R: IResultMessage]:
    """What a slot's child process runs. It is pickled into the child, so it holds only
    module-level functions, classes and picklable values."""

    name: str
    job_type: type[J]
    build_handler: Callable[[], Callable[[J], R]]
    failure_result: Callable[[J, RunFailure], R]


def slot_program[J: JobMessage, R: IResultMessage](
    spec: WorkerSpec[J, R], build_handler: Callable[[], Callable[[J], R]]
) -> SlotProgram[J, R]:
    return SlotProgram(spec.name, spec.job_type, build_handler, spec.failure_result)


def serve_slot[J: JobMessage, R: IResultMessage](
    connection: Connection, program: SlotProgram[J, R]
) -> None:
    handler = program.build_handler()
    connection.send_bytes(_READY)
    while True:
        try:
            body = connection.recv_bytes()
        except EOFError:
            return
        job = program.job_type.model_validate_json(body)
        try:
            result = handler(job)
        except Exception:
            logger.exception("Job %s failed unexpectedly", job.job_id)
            result = program.failure_result(job, RunFailure.ERRORED)
        connection.send_bytes(result.model_dump_json().encode())


class ProcessSlot[J: JobMessage, R: IResultMessage]:
    """One child process that keeps its models loaded and runs one job at a time.

    A crash or an overrun kills only the child; the next job starts a new one.
    """

    def __init__(
        self,
        program: SlotProgram[J, R],
        results: TypeAdapter[R],
        *,
        timeout: timedelta,
        startup_timeout: timedelta,
    ) -> None:
        self._program: SlotProgram[J, R] = program
        self._results: TypeAdapter[R] = results
        self._timeout: timedelta = timeout
        self._startup_timeout: timedelta = startup_timeout
        self._process: SpawnProcess | None = None
        self._connection: Connection | None = None

    async def start(self) -> None:
        # CUDA cannot be used again in a forked child, so children are always spawned.
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(
            target=serve_slot, args=(child, self._program), name=self._program.name
        )
        process.start()
        child.close()
        self._process, self._connection = process, parent
        try:
            await self._await_greeting(parent)
        except BaseException:
            await self._discard()
            raise

    async def run(self, job: J) -> R:
        connection = await self._running_connection()
        try:
            connection.send_bytes(job.model_dump_json().encode())
        except OSError:
            logger.exception("The worker process died before job %s", job.job_id)
            await self._discard()
            return self._program.failure_result(job, RunFailure.CRASHED)
        try:
            answered = await asyncio.to_thread(connection.poll, self._timeout.total_seconds())
        except asyncio.CancelledError:
            await self._discard()
            raise
        if not answered:
            logger.warning("Job %s ran past %s and was stopped", job.job_id, self._timeout)
            await self._discard()
            return self._program.failure_result(job, RunFailure.TIMED_OUT)
        try:
            body = connection.recv_bytes()
        except EOFError:
            logger.exception("The worker process died during job %s", job.job_id)
            await self._discard()
            return self._program.failure_result(job, RunFailure.CRASHED)
        return self._results.validate_json(body)

    async def stop(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if self._process is not None:
            await asyncio.to_thread(self._process.join, _STOP_GRACE_SECONDS)
        await self._discard()

    async def _await_greeting(self, connection: Connection) -> None:
        started = await asyncio.to_thread(connection.poll, self._startup_timeout.total_seconds())
        if not started:
            raise SlotStartupError("The worker process did not start in time")
        try:
            greeting = connection.recv_bytes()
        except EOFError:
            raise SlotStartupError("The worker process exited while starting") from None
        if greeting != _READY:
            raise SlotStartupError("The worker process sent an unexpected greeting")

    async def _running_connection(self) -> Connection:
        if self._process is None or not self._process.is_alive() or self._connection is None:
            await self._discard()
            await self.start()
        if self._connection is None:
            raise SlotStartupError("The worker process is not running")
        return self._connection

    async def _discard(self) -> None:
        process, connection = self._process, self._connection
        self._process, self._connection = None, None
        if connection is not None:
            connection.close()
        if process is not None:
            if process.is_alive():
                process.kill()
            await asyncio.to_thread(process.join, _STOP_GRACE_SECONDS)
            process.close()


class SlotPool[J: JobMessage, R: IResultMessage]:
    def __init__(self, slots: Sequence[ProcessSlot[J, R]]) -> None:
        self._slots: tuple[ProcessSlot[J, R], ...] = tuple(slots)
        self._idle: asyncio.Queue[ProcessSlot[J, R]] = asyncio.Queue()

    async def start(self) -> None:
        async with asyncio.TaskGroup() as group:
            for slot in self._slots:
                group.create_task(slot.start())
        for slot in self._slots:
            self._idle.put_nowait(slot)

    async def run(self, job: J) -> R:
        slot = await self._idle.get()
        try:
            return await slot.run(job)
        finally:
            self._idle.put_nowait(slot)

    async def stop(self) -> None:
        async with asyncio.TaskGroup() as group:
            for slot in self._slots:
                group.create_task(slot.stop())
