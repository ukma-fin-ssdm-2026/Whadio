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


class ProcessingFailure(StrEnum):
    TRANSCRIPTION_FAILED = "transcription_failed"
    NOTES_FAILED = "notes_failed"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_REJECTED = "provider_rejected"
    PROCESSING_TIMEOUT = "processing_timeout"
