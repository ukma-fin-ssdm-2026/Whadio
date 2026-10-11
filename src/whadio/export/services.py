from html import escape
from uuid import UUID

from ..meetings.contracts import TranscriptVersion
from ..meetings.services import MeetingService

CONSENT_NOTICE = "This content must not be shared without the participants' permission."
ATTRIBUTION = "Generated with Whadio."


def _clock(seconds: float, separator: str = ".") -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    whole_seconds, fraction = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{fraction:03d}"


class ExportService:
    def __init__(self, meetings: MeetingService) -> None:
        self._meetings: MeetingService = meetings

    async def transcript_markdown(
        self, actor_id: UUID, meeting_id: UUID, *, timestamps: bool = True
    ) -> str:
        version = await self._meetings.transcript(actor_id, meeting_id)
        names: dict[UUID | None, str] = {
            speaker.speaker_id: speaker.display_name for speaker in version.speakers
        }
        lines = [CONSENT_NOTICE, self._provenance(version)]
        for segment in version.segments:
            timestamp = f"[{_clock(float(segment.start_time_seconds))}] " if timestamps else ""
            lines.append(f"{timestamp}{names.get(segment.speaker_id, 'Unknown')}: {segment.text}")
        lines.append(ATTRIBUTION)
        return "\n\n".join(lines) + "\n"

    async def transcript_vtt(self, actor_id: UUID, meeting_id: UUID) -> str:
        version = await self._meetings.transcript(actor_id, meeting_id)
        names: dict[UUID | None, str] = {
            speaker.speaker_id: speaker.display_name for speaker in version.speakers
        }
        lines = ["WEBVTT", f"NOTE {CONSENT_NOTICE}", f"NOTE {self._provenance(version)}"]
        lines.extend(
            f"{_clock(float(segment.start_time_seconds))} --> "
            f"{_clock(float(segment.end_time_seconds))}\n"
            f"<v {escape(names.get(segment.speaker_id, 'Unknown'))}>"
            f"{escape(segment.text)}"
            for segment in version.segments
        )
        lines.append(f"NOTE {ATTRIBUTION}")
        return "\n\n".join(lines) + "\n"

    async def notes_markdown(self, actor_id: UUID, meeting_id: UUID) -> str | None:
        versions = await self._meetings.notes(actor_id, meeting_id)
        if not versions:
            return None
        current = versions[0]
        context = "\n".join(f"- {item.context_meeting_name_snapshot}" for item in current.context)
        return (
            f"{CONSENT_NOTICE}\n\n{current.note.content}\n\n"
            f"Context meetings:\n{context}\n\n{ATTRIBUTION}\n"
        )

    @staticmethod
    def _provenance(version: TranscriptVersion) -> str:
        edited = "Edited transcript. " if version.is_edited else "Original transcript. "
        return (
            f"{edited}Original transcript: /api/v1/meetings/{version.transcript.meeting_id}"
            f"/transcript?revision_id={version.original_revision_id}"
        )
