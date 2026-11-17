from datetime import datetime
from typing import Protocol
from uuid import UUID

from ..accounts.enums import NotesTemplate
from .contracts import QueuedNotes


class IMeetingProcessing(Protocol):
    async def queue_transcription(self, meeting_id: UUID) -> None:
        """Persist the job and durable publication intent in the caller's transaction."""
        ...

    async def queue_notes(
        self,
        meeting_id: UUID,
        requester_id: UUID,
        preset: NotesTemplate | None,
        *,
        use_builtin_model: bool,
        now: datetime,
    ) -> QueuedNotes:
        """Reserve a notes job in this transaction; nothing is published before the commit.

        Processing checks that the requester can read the meeting and locks it, then refuses a
        meeting without a transcript (`NOT_TRANSCRIBED`), one with a notes job queued or running
        (`NOTES_IN_PROGRESS`) and one that used up its regenerations (`REGENERATION_LIMIT`).
        Otherwise the meeting becomes `processing` and its regeneration count rises by one. The
        job keeps the preset, the workspace's default when none is given, and the requester
        across retries. Its request is built at publication from the current transcript
        revision, edits included, and the notes are saved, as the requester's, only when the
        job succeeds. `use_builtin_model` is refused with `INTEGRATION_UNAVAILABLE` until FR-023
        is built.
        """
        ...
