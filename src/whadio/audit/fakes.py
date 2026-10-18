from typing import override

from .contracts import ContentEvent, IContentAuditWriter


class RecordingAuditWriter(IContentAuditWriter):
    def __init__(self) -> None:
        self.events: list[ContentEvent] = []

    @override
    async def write(self, event: ContentEvent) -> None:
        self.events.append(event)
