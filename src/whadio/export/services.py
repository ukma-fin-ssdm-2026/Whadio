import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from html import escape
from typing import Protocol
from urllib.parse import quote
from uuid import UUID

from ..meetings.contracts import NoteVersion, TranscriptVersion
from ..shared.pagination import ListWindow

CONSENT_NOTICE = "This content must not be shared without the participants' permission."
ATTRIBUTION = "Generated with Whadio."


class ExportFormat(StrEnum):
    MARKDOWN = "markdown"
    VTT = "vtt"


class ExportVersion(StrEnum):
    CURRENT = "current"
    ORIGINAL = "original"


class IExportMeetings(Protocol):
    async def transcript(
        self, actor_id: UUID, meeting_id: UUID, revision_id: UUID | None = None
    ) -> TranscriptVersion: ...

    async def notes(
        self, actor_id: UUID, meeting_id: UUID, page: ListWindow | None = None
    ) -> list[NoteVersion]: ...


@dataclass(frozen=True)
class TranscriptExport:
    content: str
    original_view: str
    original_download: str


def _clock(seconds: Decimal) -> str:
    milliseconds = int((seconds * 1000).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    whole_seconds, fraction = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{fraction:03d}"


def _markdown(text: str) -> str:
    text = escape(text, quote=False).replace("\\", "\\\\")
    text = re.sub(r"([`*\[\]|])", r"\\\1", text)
    text = re.sub(r"(?<!\w)_|_(?!\w)", r"\\_", text)
    text = text.replace("~~", r"\~\~")
    text = re.sub(r"(?m)^( {0,3})([#\-+])(?=\s|[#\-]|$)", r"\1\\\2", text)
    text = re.sub(r"(?m)^( {0,3}\d{1,9})([.)])(?=\s|$)", r"\1\\\2", text)
    return re.sub(r"(?m)^( {0,3})([=-])(?=[=-]*[ \t]*$)", r"\1\\\2", text)


def _cue(text: str) -> str:
    # Empty lines terminate a WebVTT cue; retain paragraph breaks as nonempty lines.
    return "\n".join(line or "\u200b" for line in escape(text, quote=False).splitlines())


class ExportService:
    def __init__(
        self, meetings: IExportMeetings, public_origin: str, api_public_origin: str | None = None
    ) -> None:
        self._meetings: IExportMeetings = meetings
        self._origin: str = quote(public_origin.rstrip("/"), safe=":/%[]@!$&'*,;=~._-")
        self._api_origin: str = quote(
            (api_public_origin or public_origin).rstrip("/"), safe=":/%[]@!$&'*,;=~._-"
        )

    async def transcript(
        self,
        actor_id: UUID,
        meeting_id: UUID,
        export_format: ExportFormat = ExportFormat.MARKDOWN,
        version: ExportVersion = ExportVersion.CURRENT,
        *,
        timestamps: bool = True,
    ) -> TranscriptExport:
        found = await self._meetings.transcript(actor_id, meeting_id)
        if (
            version == ExportVersion.ORIGINAL
            and found.revision.revision_id != found.original_revision_id
        ):
            found = await self._meetings.transcript(
                actor_id, meeting_id, found.original_revision_id
            )
        base = f"{self._api_origin}/api/v1/meetings/{meeting_id}/transcript"
        original_view = (
            f"{self._origin}/meetings/{meeting_id}?revision_id={found.original_revision_id}"
        )
        original_download = f"{base}/export?version=original&format={export_format}"
        if export_format == ExportFormat.MARKDOWN:
            original_download += f"&timestamps={str(timestamps).lower()}"
        label = "Original" if found.revision.revision_id == found.original_revision_id else "Edited"
        provenance = f"{label} transcript."
        names: dict[UUID | None, str] = {
            speaker.speaker_id: speaker.display_name for speaker in found.speakers
        }
        if export_format == ExportFormat.VTT:
            lines = [
                "WEBVTT",
                f"NOTE {CONSENT_NOTICE}",
                (
                    f"NOTE {provenance}\nOriginal view: {original_view}\n"
                    f"Original download: {original_download}"
                ),
            ]
            for segment in found.segments:
                start = segment.start_time_seconds
                # Sub-millisecond stored segments must still have a positive exported cue duration.
                end = max(segment.end_time_seconds, start + Decimal("0.001"))
                speaker = escape(
                    " ".join(names.get(segment.speaker_id, "Unknown").split()), quote=False
                )
                lines.append(
                    f"{_clock(start)} --> {_clock(end)}\n<v {speaker}>{_cue(segment.text)}</v>"
                )
            lines.append(f"NOTE {ATTRIBUTION}")
        else:
            lines = [
                CONSENT_NOTICE,
                provenance,
                (
                    f"[Original transcript]({original_view}) | "
                    f"[Download original]({original_download})"
                ),
            ]
            for segment in found.segments:
                timestamp = f"[{_clock(segment.start_time_seconds)}] " if timestamps else ""
                speaker = _markdown(" ".join(names.get(segment.speaker_id, "Unknown").split()))
                text = _markdown(segment.text).replace("\n", "  \n")
                lines.append(f"{timestamp}{speaker}: {text}")
            lines.append(ATTRIBUTION)
        return TranscriptExport("\n\n".join(lines) + "\n", original_view, original_download)

    async def notes_markdown(self, actor_id: UUID, meeting_id: UUID) -> str | None:
        versions = await self._meetings.notes(actor_id, meeting_id, ListWindow(1))
        if not versions:
            return None
        current = versions[0]
        context = "\n".join(
            f"- {_markdown(item.context_meeting_name_snapshot)}" for item in current.context
        )
        return (
            f"{CONSENT_NOTICE}\n\n{current.note.content}\n\n"
            f"Context meetings:\n{context or 'None.'}\n\n{ATTRIBUTION}\n"
        )
