from enum import StrEnum


class MeetingSource(StrEnum):
    EXTENSION = "extension"
    UPLOAD = "upload"


class RecordingStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"


class ProcessingState(StrEnum):
    RECORDING = "recording"
    QUEUED = "queued"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class AccessMode(StrEnum):
    WORKSPACE = "workspace"
    RESTRICTED = "restricted"


class RevisionType(StrEnum):
    ORIGINAL = "original"
    EDITED = "edited"
