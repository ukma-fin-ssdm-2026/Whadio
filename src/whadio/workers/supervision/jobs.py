from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from ...contracts.common import JobKind, JobMessage
from ...contracts.queues import QueueSpec


class RunFailure(StrEnum):
    CRASHED = "crashed"
    TIMED_OUT = "timed_out"
    ERRORED = "errored"


class IResultMessage(Protocol):
    @property
    def type(self) -> str: ...

    @property
    def job_id(self) -> UUID: ...

    def model_dump_json(self) -> str: ...


@dataclass(frozen=True, slots=True)
class WorkerSpec[J: JobMessage, R: IResultMessage]:
    name: str
    queue: QueueSpec
    kind: JobKind
    job_type: type[J]
    failure_result: Callable[[J, RunFailure], R]


class IJobRunner[J: JobMessage, R: IResultMessage](Protocol):
    async def start(self) -> None: ...

    async def run(self, job: J, /) -> R: ...

    async def stop(self) -> None: ...
