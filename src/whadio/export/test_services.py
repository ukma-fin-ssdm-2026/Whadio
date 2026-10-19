import asyncio
from decimal import Decimal
from io import BytesIO
from uuid import UUID, uuid4

import av
import pytest
from pydantic import ValidationError

from ..meetings.contracts import NoteVersion, TranscriptVersion
from ..meetings.enums import RevisionType
from ..meetings.models import (
    Note,
    NoteContextMeeting,
    Speaker,
    Transcript,
    TranscriptRevision,
    TranscriptSegment,
)
from ..shared.pagination import ListWindow
from .services import ATTRIBUTION, CONSENT_NOTICE, ExportFormat, ExportService, ExportVersion
from .settings import ExportSettings


class ExportMeetings:
    def __init__(self, text: str = "Original text", speaker: str = "Alice") -> None:
        self.meeting: UUID = uuid4()
        original_id, edited_id, speaker_id, transcript_id = (uuid4() for _ in range(4))
        transcript = Transcript(
            meeting_id=self.meeting, transcript_id=transcript_id, current_revision_id=edited_id
        )
        self.original: TranscriptVersion = TranscriptVersion(
            transcript,
            TranscriptRevision(revision_id=original_id, revision_type=RevisionType.ORIGINAL),
            original_revision_id=original_id,
            is_edited=True,
            speakers=[Speaker(speaker_id=speaker_id, display_name=speaker)],
            segments=[
                TranscriptSegment(
                    start_time_seconds=Decimal("59.9995"),
                    end_time_seconds=Decimal("60.0001"),
                    speaker_id=speaker_id,
                    text=text,
                )
            ],
        )
        self.current: TranscriptVersion = TranscriptVersion(
            transcript,
            TranscriptRevision(revision_id=edited_id, revision_type=RevisionType.EDITED),
            original_revision_id=original_id,
            is_edited=True,
            speakers=[Speaker(speaker_id=speaker_id, display_name="Corrected speaker")],
            segments=[
                TranscriptSegment(
                    start_time_seconds=Decimal(0),
                    end_time_seconds=Decimal(1),
                    speaker_id=speaker_id,
                    text="Corrected text",
                )
            ],
        )
        self.note_versions: list[NoteVersion] = []
        self.note_page: ListWindow | None = None

    async def transcript(
        self, actor_id: UUID, meeting_id: UUID, revision_id: UUID | None = None
    ) -> TranscriptVersion:
        del actor_id, meeting_id
        return self.original if revision_id == self.original.original_revision_id else self.current

    async def notes(
        self, actor_id: UUID, meeting_id: UUID, page: ListWindow | None = None
    ) -> list[NoteVersion]:
        del actor_id, meeting_id
        self.note_page = page
        return self.note_versions


@pytest.mark.parametrize("export_format", list(ExportFormat))
def test_current_export_carries_corrected_speaker_and_text(export_format: ExportFormat) -> None:
    # Arrange
    meetings = ExportMeetings()
    # Act
    document = asyncio.run(
        ExportService(meetings, "https://whadio.example").transcript(
            uuid4(), meetings.meeting, export_format
        )
    )
    # Assert
    assert all(
        value in document.content
        for value in (
            "Corrected speaker",
            "Corrected text",
            "Edited transcript.",
            CONSENT_NOTICE,
            ATTRIBUTION,
        )
    )


@pytest.mark.parametrize("export_format", list(ExportFormat))
def test_original_export_is_never_labelled_edited(export_format: ExportFormat) -> None:
    # Arrange
    meetings = ExportMeetings()
    # Act
    document = asyncio.run(
        ExportService(meetings, "https://whadio.example").transcript(
            uuid4(), meetings.meeting, export_format, ExportVersion.ORIGINAL
        )
    )
    # Assert
    assert (
        "Original text" in document.content,
        "Original transcript." in document.content,
        "Edited transcript." in document.content,
    ) == (True, True, False)


def test_markdown_can_omit_timestamps_without_omitting_speakers() -> None:
    # Arrange
    meetings = ExportMeetings()
    # Act
    document = asyncio.run(
        ExportService(meetings, "https://whadio.example").transcript(
            uuid4(), meetings.meeting, timestamps=False
        )
    )
    # Assert
    assert (
        "[00:00:00.000]" in document.content,
        "Corrected speaker: Corrected text" in document.content,
    ) == (False, True)


def test_vtt_is_timed_even_when_markdown_timestamps_are_disabled() -> None:
    # Arrange
    meetings = ExportMeetings()
    # Act
    document = asyncio.run(
        ExportService(meetings, "https://whadio.example").transcript(
            uuid4(), meetings.meeting, ExportFormat.VTT, timestamps=False
        )
    )
    # Assert
    assert "00:00:00.000 --> 00:00:01.000" in document.content


def test_vtt_rounding_keeps_submillisecond_cues_positive() -> None:
    # Arrange
    meetings = ExportMeetings()
    # Act
    document = asyncio.run(
        ExportService(meetings, "https://whadio.example").transcript(
            uuid4(), meetings.meeting, ExportFormat.VTT, ExportVersion.ORIGINAL
        )
    )
    # Assert
    assert "00:01:00.000 --> 00:01:00.001" in document.content


def test_vtt_untrusted_payload_cannot_add_cues_or_markup() -> None:
    # Arrange
    meetings = ExportMeetings(
        (
            "\u041f\u0440\u0438\u0432\u0456\u0442\n\n"
            "00:00:02.000 --> 00:00:03.000\n<script>bad</script>"
        ),
        "<b>Speaker</b>",
    )
    # Act
    document = asyncio.run(
        ExportService(meetings, "https://whadio.example").transcript(
            uuid4(), meetings.meeting, ExportFormat.VTT, ExportVersion.ORIGINAL
        )
    )
    with av.open(BytesIO(document.content.encode()), format="webvtt", mode="r") as container:
        cues = [packet for packet in container.demux() if packet.size]
    # Assert
    assert (len(cues), "<script>" in document.content, "--&gt;" in document.content) == (
        1,
        False,
        True,
    )


def test_markdown_keeps_user_markup_inert() -> None:
    # Arrange
    meetings = ExportMeetings("[link](https://evil.example)\n# heading\n<script>x</script>")
    # Act
    document = asyncio.run(
        ExportService(meetings, "https://whadio.example").transcript(
            uuid4(), meetings.meeting, version=ExportVersion.ORIGINAL
        )
    )
    # Assert
    assert all(
        value not in document.content
        for value in ("[link](https://evil.example)", "\n# heading", "<script>")
    )


def test_original_links_use_configured_origin_and_selected_format() -> None:
    # Arrange
    meetings = ExportMeetings()
    # Act
    document = asyncio.run(
        ExportService(meetings, "https://whadio.example/").transcript(
            uuid4(), meetings.meeting, ExportFormat.VTT
        )
    )
    # Assert
    assert (document.original_view, document.original_download) == (
        f"https://whadio.example/api/v1/meetings/{meetings.meeting}/transcript?revision_id={meetings.original.original_revision_id}",
        f"https://whadio.example/api/v1/meetings/{meetings.meeting}/transcript/export?version=original&format=vtt",
    )


def test_notes_export_uses_a_bounded_current_note_query() -> None:
    # Arrange
    meetings = ExportMeetings()
    meetings.note_versions = [
        NoteVersion(
            Note(content="Saved notes"),
            [
                NoteContextMeeting(
                    context_meeting_name_snapshot="Deleted context", context_meeting_id=None
                )
            ],
        )
    ]
    # Act
    content = asyncio.run(
        ExportService(meetings, "https://whadio.example").notes_markdown(uuid4(), meetings.meeting)
    )
    # Assert
    assert (meetings.note_page, content) == (
        ListWindow(1),
        (
            f"{CONSENT_NOTICE}\n\nSaved notes\n\n"
            f"Context meetings:\n- Deleted context\n\n{ATTRIBUTION}\n"
        ),
    )


def test_missing_notes_export_has_no_placeholder_content() -> None:
    # Arrange
    meetings = ExportMeetings()
    # Act
    content = asyncio.run(
        ExportService(meetings, "https://whadio.example").notes_markdown(uuid4(), meetings.meeting)
    )
    # Assert
    assert content is None


@pytest.mark.parametrize(
    "origin",
    [
        "https://user:password@example.com",
        "https://example.com/path",
        "https://example.com?query=1",
        "https://example.com#fragment",
    ],
)
def test_canonical_origin_refuses_credentials_and_nonorigin_components(origin: str) -> None:
    # Arrange
    # Act
    with pytest.raises(ValidationError) as failure:
        ExportSettings.model_validate({"public_origin": origin})
    # Assert
    assert failure.value.error_count() == 1


def test_unassigned_segments_export_with_an_unknown_speaker_label() -> None:
    # Arrange
    meetings = ExportMeetings()
    meetings.current.segments[0].speaker_id = None
    # Act
    document = asyncio.run(
        ExportService(meetings, "https://whadio.example").transcript(uuid4(), meetings.meeting)
    )
    # Assert
    assert "Unknown: Corrected text" in document.content


@pytest.mark.parametrize("export_format", list(ExportFormat))
def test_empty_transcript_keeps_notice_provenance_and_attribution(
    export_format: ExportFormat,
) -> None:
    # Arrange
    meetings = ExportMeetings()
    meetings.current.segments.clear()
    # Act
    document = asyncio.run(
        ExportService(meetings, "https://whadio.example").transcript(
            uuid4(), meetings.meeting, export_format
        )
    )
    # Assert
    assert all(
        value in document.content for value in (CONSENT_NOTICE, "Edited transcript.", ATTRIBUTION)
    )


def test_vtt_keeps_apostrophes_in_speaker_annotations() -> None:
    # Arrange
    meetings = ExportMeetings(speaker="O'Connor")
    # Act
    document = asyncio.run(
        ExportService(meetings, "https://whadio.example").transcript(
            uuid4(), meetings.meeting, ExportFormat.VTT, ExportVersion.ORIGINAL
        )
    )
    # Assert
    assert "<v O'Connor>" in document.content
