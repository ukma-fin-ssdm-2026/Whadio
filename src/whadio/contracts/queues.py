from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final


@dataclass(frozen=True, slots=True)
class QueueSpec:
    name: str
    arguments: Mapping[str, str | int]


DEAD_LETTERS: Final = QueueSpec(
    "processing.dead-letters", MappingProxyType({"x-queue-type": "quorum"})
)

# Every side declares these queues with exactly these arguments: RabbitMQ refuses a declaration
# whose arguments differ from those of the existing queue.
_WORK_QUEUE_ARGUMENTS: Final = MappingProxyType(
    {
        "x-queue-type": "quorum",
        "x-delivery-limit": 5,
        "x-dead-letter-exchange": "",
        "x-dead-letter-routing-key": DEAD_LETTERS.name,
        "x-dead-letter-strategy": "at-least-once",
        # Required by at-least-once dead-lettering.
        "x-overflow": "reject-publish",
    }
)

TRANSCRIPTION_REQUESTS: Final = QueueSpec("transcription.requests", _WORK_QUEUE_ARGUMENTS)
NOTES_REQUESTS: Final = QueueSpec("notes.requests", _WORK_QUEUE_ARGUMENTS)
PROCESSING_RESULTS: Final = QueueSpec("processing.results", _WORK_QUEUE_ARGUMENTS)

ALL_QUEUES: Final = (DEAD_LETTERS, TRANSCRIPTION_REQUESTS, NOTES_REQUESTS, PROCESSING_RESULTS)
