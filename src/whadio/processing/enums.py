from enum import StrEnum


class JobType(StrEnum):
    TRANSCRIPTION = "transcription"
    NOTES = "notes"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ProcessingOutcome(StrEnum):
    FINISHED = "finished"
    FAILED = "failed"
