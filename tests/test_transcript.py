from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from whadio.api.accounts.fixtures import ALICE, DEMO_EMAIL, DEMO_PASSWORD
from whadio.api.meetings.fixtures import DESIGN_SYNC_MEETING_ID, SPRINT_12_MEETING_ID
from whadio.api.meetings.models import Speaker, Transcript, TranscriptRevision, TranscriptSegment
from whadio.api.meetings.schemas import RevisionType

SPRINT_12_TRANSCRIPT = f"/api/v1/meetings/{SPRINT_12_MEETING_ID}/transcript"


def sign_in_as_alice(client: TestClient) -> None:
    client.post("/api/v1/sessions", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})


def test_transcript_comes_from_the_database(client: TestClient) -> None:
    sign_in_as_alice(client)

    body = client.get(SPRINT_12_TRANSCRIPT).json()

    assert body["meeting_id"] == str(SPRINT_12_MEETING_ID)
    assert body["language"] == "uk"
    assert body["revision"]["revision_type"] == "original"
    assert body["revision"]["is_current"] is True
    assert body["original_revision_id"] == body["revision"]["id"]
    assert body["is_edited"] is False
    assert [(s["display_name"], s["is_unnamed"]) for s in body["speakers"]] == [
        ("Alice", False),
        ("Speaker 2", True),
    ]
    assert body["has_unnamed_speakers"] is True
    # In time order, each pointing at one of this revision's speakers.
    starts = [segment["start_seconds"] for segment in body["segments"]]
    assert starts == sorted(starts) and len(starts) == 3
    speaker_ids = {speaker["id"] for speaker in body["speakers"]}
    assert {segment["speaker_id"] for segment in body["segments"]} <= speaker_ids


def test_meeting_without_transcript_is_409(client: TestClient) -> None:
    sign_in_as_alice(client)

    response = client.get(f"/api/v1/meetings/{DESIGN_SYNC_MEETING_ID}/transcript")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NOT_TRANSCRIBED"


def test_edited_revision_is_shown_and_the_original_stays_reachable(client: TestClient) -> None:
    sign_in_as_alice(client)
    original_id = client.get(SPRINT_12_TRANSCRIPT).json()["revision"]["id"]

    async def add_edited_revision() -> None:
        async with client.app.state.sessionmaker() as db:
            transcript = await db.scalar(
                select(Transcript).where(Transcript.meeting_id == SPRINT_12_MEETING_ID)
            )
            edited = TranscriptRevision(
                revision_id=uuid4(),
                transcript_id=transcript.transcript_id,
                revision_type=RevisionType.EDITED,
                edited_by_user_id=ALICE.id,
                created_at=datetime.now(UTC),
            )
            speaker = Speaker(
                speaker_id=uuid4(), revision_id=edited.revision_id, display_name="Bob"
            )
            db.add_all([edited, speaker])
            db.add(
                TranscriptSegment(
                    revision_id=edited.revision_id,
                    speaker_id=speaker.speaker_id,
                    start_time_seconds=0.0,
                    end_time_seconds=1.0,
                    text="Edited line.",
                )
            )
            transcript.current_revision_id = edited.revision_id
            await db.commit()

    client.portal.call(add_edited_revision)
    body = client.get(SPRINT_12_TRANSCRIPT).json()

    assert body["revision"]["revision_type"] == "edited"
    assert body["revision"]["edited_by_user_id"] == str(ALICE.id)
    assert body["original_revision_id"] == original_id
    assert body["is_edited"] is True
    assert body["has_unnamed_speakers"] is False
    assert [segment["text"] for segment in body["segments"]] == ["Edited line."]
