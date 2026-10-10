from ...contracts.transcription import TranscriptionFailure


class TranscriptionError(Exception):
    def __init__(self, reason: TranscriptionFailure) -> None:
        super().__init__(reason.value)
        self.reason: TranscriptionFailure = reason
