from ...contracts.notes import NotesFailure


class NotesError(Exception):
    def __init__(self, reason: NotesFailure) -> None:
        super().__init__(reason.value)
        self.reason: NotesFailure = reason
