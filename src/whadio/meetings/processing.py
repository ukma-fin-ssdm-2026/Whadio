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
        """Reserve a notes job in this transaction; do not publish before commit.

        Processing authorizes and locks the meeting, checks job state and regeneration limits,
        and persists its state/count decision through Meetings. It selects the provider and
        snapshots the current transcript, unrestricted same-folder context and glossary.
        It retains the requester and requested preset across
        retries, and persists results through Meetings only for a successfully completed job.
        """
        ...
