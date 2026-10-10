import io
import wave
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from anyio.from_thread import BlockingPortal
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..accounts.fixtures import (
    ALICE,
    DEMO_EMAIL,
    DEMO_PASSWORD,
    PERSONAL_WORKSPACE_ID,
    TEAM_WORKSPACE_ID,
)
from ..accounts.models import WorkspaceMembership
from ..accounts.schemas import Role, WorkspaceRead
from ..audit.models import AuditAction, AuditEvent
from ..conftest import BOB_EMAIL, BOB_PASSWORD
from ..core.schemas import Page
from .fixtures import (
    DESIGN_SYNC_MEETING_ID,
    PERSONAL_FOLDER_ID,
    SPRINT_11_MEETING_ID,
    SPRINT_12_MEETING_ID,
    SPRINT_FOLDER_ID,
    TEAM_DEFAULT_FOLDER_ID,
)
from .models import Folder, Meeting, Speaker, Transcript, TranscriptRevision, TranscriptSegment
from .schemas import (
    MeetingRead,
    MeetingSummary,
    ProcessingState,
    RevisionType,
    SourceType,
    TranscriptRead,
)

TEAM_MEETINGS = f"/api/v1/workspaces/{TEAM_WORKSPACE_ID}/meetings"
# "Thesis consultation", the demo meeting in Alice's personal workspace.
THESIS_MEETING_ID = UUID("6e5d4c3b-2a19-4807-96f5-e4d3c2b1a090")


def sign_in_as_alice(client: TestClient) -> None:
    client.post("/api/v1/sessions", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})


def ids(client: TestClient, params: dict[str, str] | None = None) -> list[str]:
    page = Page[MeetingSummary].model_validate_json(client.get(TEAM_MEETINGS, params=params).text)
    return [str(item.id) for item in page.items]


def test_list_is_newest_recording_first(client: TestClient) -> None:
    sign_in_as_alice(client)

    response = client.get(TEAM_MEETINGS)

    assert response.status_code == 200
    # Recorded 2 October, 30 September and 16 September.
    items = Page[MeetingSummary].model_validate_json(response.text).items
    assert [item.id for item in items] == [
        DESIGN_SYNC_MEETING_ID,
        SPRINT_12_MEETING_ID,
        SPRINT_11_MEETING_ID,
    ]
    assert items[0].processing_state is ProcessingState.QUEUED
    assert items[0].workspace_id == TEAM_WORKSPACE_ID


def test_name_filter_ignores_case(client: TestClient) -> None:
    sign_in_as_alice(client)

    assert ids(client, {"name": "SPRINT"}) == [str(SPRINT_12_MEETING_ID), str(SPRINT_11_MEETING_ID)]


def test_name_filter_treats_percent_literally(client: TestClient) -> None:
    sign_in_as_alice(client)

    # In SQL LIKE, % matches anything; here it must only match a real percent sign.
    assert ids(client, {"name": "%"}) == []


def test_date_range_includes_from_and_excludes_to(client: TestClient) -> None:
    sign_in_as_alice(client)

    params = {"recorded_from": "2026-09-30T10:00:00Z", "recorded_to": "2026-10-02T14:00:00Z"}

    assert ids(client, params) == [str(SPRINT_12_MEETING_ID)]


def test_folder_filter(client: TestClient) -> None:
    sign_in_as_alice(client)

    # All three team meetings are in the sprint folder; the default one is empty.
    assert ids(client, {"folder_id": str(TEAM_DEFAULT_FOLDER_ID)}) == []


def test_only_this_workspaces_meetings(client: TestClient) -> None:
    sign_in_as_alice(client)

    listed = client.get(f"/api/v1/workspaces/{PERSONAL_WORKSPACE_ID}/meetings")

    items = Page[MeetingSummary].model_validate_json(listed.text).items
    assert [item.name for item in items] == ["Thesis consultation"]


@pytest.mark.usefixtures("bob")
def test_non_member_gets_404(client: TestClient) -> None:
    client.post("/api/v1/sessions", json={"email": BOB_EMAIL, "password": BOB_PASSWORD})

    response = client.get(f"/api/v1/workspaces/{PERSONAL_WORKSPACE_ID}/meetings")

    assert response.status_code == 404
    assert client.get(TEAM_MEETINGS).status_code == 200


def test_list_needs_sign_in(client: TestClient) -> None:
    assert client.get(TEAM_MEETINGS).status_code == 401


@pytest.mark.usefixtures("bob")
def test_new_workspace_and_new_account_get_a_default_folder(
    client: TestClient, sessionmaker: async_sessionmaker[AsyncSession], portal: BlockingPortal
) -> None:
    sign_in_as_alice(client)
    created = WorkspaceRead.model_validate_json(
        client.post("/api/v1/workspaces", json={"name": "Research"}).text
    )

    async def folders() -> list[Folder]:
        async with sessionmaker() as db:
            return [*await db.scalars(select(Folder).where(Folder.is_default))]

    default_folders = [folder.workspace_id for folder in portal.call(folders)]
    assert created.id in default_folders
    # Alice's two seeded workspaces, "Research" and Bob's personal one: one default folder each.
    assert len(default_folders) == len(set(default_folders)) == 4


def test_deleting_a_workspace_deletes_its_folders_and_meetings(
    client: TestClient, sessionmaker: async_sessionmaker[AsyncSession], portal: BlockingPortal
) -> None:
    sign_in_as_alice(client)

    client.delete(f"/api/v1/workspaces/{TEAM_WORKSPACE_ID}")

    async def left() -> tuple[list[Folder], list[Meeting]]:
        async with sessionmaker() as db:
            folders = [*await db.scalars(select(Folder))]
            meetings = [*await db.scalars(select(Meeting))]
            return folders, meetings

    folders, meetings = portal.call(left)
    assert {folder.workspace_id for folder in folders} == {PERSONAL_WORKSPACE_ID}
    assert [meeting.name for meeting in meetings] == ["Thesis consultation"]


def wav_bytes() -> bytes:
    """A tenth of a second of silence: the smallest file the audio check accepts."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(16_000)
        recording.writeframes(b"\0\0" * 1_600)
    return buffer.getvalue()


def test_upload_saves_the_file_and_a_queued_meeting(
    client: TestClient, sessionmaker: async_sessionmaker[AsyncSession], portal: BlockingPortal
) -> None:
    sign_in_as_alice(client)
    audio = wav_bytes()

    response = client.post(
        TEAM_MEETINGS, files={"file": ("call.wav", audio, "audio/wav")}, data={"name": "Standup"}
    )

    assert response.status_code == 201
    created = MeetingRead.model_validate_json(response.text)
    assert created.name == "Standup"
    assert created.name_is_generated is False
    assert created.processing_state is ProcessingState.QUEUED
    assert created.source_type is SourceType.UPLOAD
    assert created.folder_id == TEAM_DEFAULT_FOLDER_ID
    assert response.headers["Location"].endswith(f"/meetings/{created.id}")
    # The row is stored, so the list shows it, newest first.
    assert ids(client)[0] == str(created.id)

    async def stored() -> Meeting:
        async with sessionmaker() as db:
            return await db.get_one(Meeting, created.id)

    meeting = portal.call(stored)
    assert meeting.storage_path is not None
    assert Path(meeting.storage_path).read_bytes() == audio


def test_upload_without_name_gets_a_generated_one(client: TestClient) -> None:
    sign_in_as_alice(client)

    created = MeetingRead.model_validate_json(
        client.post(TEAM_MEETINGS, files={"file": ("call.wav", wav_bytes(), "audio/wav")}).text
    )

    assert created.name.startswith("Meeting ")
    assert created.name_is_generated is True


def test_upload_into_a_chosen_folder(client: TestClient) -> None:
    sign_in_as_alice(client)

    created = MeetingRead.model_validate_json(
        client.post(
            TEAM_MEETINGS,
            files={"file": ("call.wav", wav_bytes(), "audio/wav")},
            data={"folder_id": str(SPRINT_FOLDER_ID)},
        ).text
    )

    assert created.folder_id == SPRINT_FOLDER_ID


def test_upload_into_another_workspaces_folder_is_422(client: TestClient) -> None:
    sign_in_as_alice(client)

    response = client.post(
        TEAM_MEETINGS,
        files={"file": ("call.wav", wav_bytes(), "audio/wav")},
        data={"folder_id": str(PERSONAL_FOLDER_ID)},
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "folder_id"


def test_upload_that_is_not_audio_is_415_and_creates_nothing(client: TestClient) -> None:
    sign_in_as_alice(client)

    response = client.post(TEAM_MEETINGS, files={"file": ("call.wav", b"not audio", "audio/wav")})

    assert response.status_code == 415
    assert len(ids(client)) == 3


@pytest.mark.usefixtures("bob")
def test_upload_by_non_member_is_404(client: TestClient) -> None:
    client.post("/api/v1/sessions", json={"email": BOB_EMAIL, "password": BOB_PASSWORD})

    response = client.post(
        f"/api/v1/workspaces/{PERSONAL_WORKSPACE_ID}/meetings",
        files={"file": ("call.wav", wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 404


def test_uploaded_meeting_can_be_opened_from_location(client: TestClient) -> None:
    sign_in_as_alice(client)
    response = client.post(TEAM_MEETINGS, files={"file": ("call.wav", wav_bytes(), "audio/wav")})

    opened = client.get(response.headers["Location"])

    assert opened.status_code == 200
    assert opened.json() == response.json()


def test_seeded_meeting_reads_from_the_database(client: TestClient) -> None:
    sign_in_as_alice(client)

    opened = MeetingRead.model_validate_json(
        client.get(f"/api/v1/meetings/{SPRINT_12_MEETING_ID}").text
    )

    assert opened.name == "Sprint 12 review"
    assert opened.workspace_id == TEAM_WORKSPACE_ID
    assert opened.processing_state is ProcessingState.PROCESSED
    # Seeded meetings have no file saved.
    assert opened.recording_available is False


def test_unknown_meeting_is_404(client: TestClient) -> None:
    sign_in_as_alice(client)

    response = client.get("/api/v1/meetings/00000000-0000-4000-8000-000000000000")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.usefixtures("bob")
def test_non_member_cannot_reach_a_meeting_by_its_id(client: TestClient) -> None:
    """Regression test for the meeting-id IDOR: every route that takes a meeting id."""
    client.post("/api/v1/sessions", json={"email": BOB_EMAIL, "password": BOB_PASSWORD})
    alices_meeting = f"/api/v1/meetings/{THESIS_MEETING_ID}"

    for response in (
        client.get(alices_meeting),
        client.patch(alices_meeting, json={"name": "Taken"}),
        client.delete(alices_meeting),
        client.get(f"{alices_meeting}/transcript"),
        client.get(f"{alices_meeting}/notes"),
        client.post(f"{alices_meeting}/notes", json={}),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.usefixtures("bob")
def test_member_can_reach_a_meeting_of_their_workspace(client: TestClient) -> None:
    client.post("/api/v1/sessions", json={"email": BOB_EMAIL, "password": BOB_PASSWORD})

    assert client.get(f"/api/v1/meetings/{SPRINT_12_MEETING_ID}").status_code == 200
    assert client.get(f"/api/v1/meetings/{SPRINT_12_MEETING_ID}/transcript").status_code == 200


def audit_events(
    sessionmaker: async_sessionmaker[AsyncSession], portal: BlockingPortal
) -> list[AuditEvent]:
    async def read() -> list[AuditEvent]:
        async with sessionmaker() as db:
            return [*await db.scalars(select(AuditEvent))]

    return portal.call(read)


def test_owner_deletes_a_meeting_and_it_is_audited(
    client: TestClient, sessionmaker: async_sessionmaker[AsyncSession], portal: BlockingPortal
) -> None:
    sign_in_as_alice(client)

    assert client.delete(f"/api/v1/meetings/{SPRINT_11_MEETING_ID}").status_code == 204

    assert client.get(f"/api/v1/meetings/{SPRINT_11_MEETING_ID}").status_code == 404
    assert str(SPRINT_11_MEETING_ID) not in ids(client)
    [event] = audit_events(sessionmaker, portal)
    assert event.action is AuditAction.MEETING_DELETED
    assert event.meeting_id == SPRINT_11_MEETING_ID
    assert event.workspace_id == TEAM_WORKSPACE_ID
    assert event.actor_user_id == ALICE.id


@pytest.mark.usefixtures("bob")
def test_plain_member_cannot_delete_someone_elses_meeting(
    client: TestClient, sessionmaker: async_sessionmaker[AsyncSession], portal: BlockingPortal
) -> None:
    client.post("/api/v1/sessions", json={"email": BOB_EMAIL, "password": BOB_PASSWORD})

    response = client.delete(f"/api/v1/meetings/{SPRINT_12_MEETING_ID}")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INSUFFICIENT_ROLE"
    assert client.get(f"/api/v1/meetings/{SPRINT_12_MEETING_ID}").status_code == 200
    assert audit_events(sessionmaker, portal) == []


@pytest.mark.usefixtures("bob")
def test_plain_member_deletes_their_own_upload_and_its_file(
    client: TestClient, sessionmaker: async_sessionmaker[AsyncSession], portal: BlockingPortal
) -> None:
    client.post("/api/v1/sessions", json={"email": BOB_EMAIL, "password": BOB_PASSWORD})
    created = MeetingRead.model_validate_json(
        client.post(TEAM_MEETINGS, files={"file": ("call.wav", wav_bytes(), "audio/wav")}).text
    )

    async def storage_path() -> Path:
        async with sessionmaker() as db:
            meeting = await db.get_one(Meeting, created.id)
            assert meeting.storage_path is not None
            return Path(meeting.storage_path)

    saved = portal.call(storage_path)
    assert saved.exists()

    assert client.delete(f"/api/v1/meetings/{created.id}").status_code == 204

    assert not saved.exists()
    assert client.get(f"/api/v1/meetings/{created.id}").status_code == 404


def test_moderator_deletes_someone_elses_meeting(
    client: TestClient,
    bob: UUID,
    sessionmaker: async_sessionmaker[AsyncSession],
    portal: BlockingPortal,
) -> None:
    async def make_bob_moderator() -> None:
        async with sessionmaker() as db:
            membership = (
                await db.scalars(
                    select(WorkspaceMembership).where(
                        WorkspaceMembership.workspace_id == TEAM_WORKSPACE_ID,
                        WorkspaceMembership.user_id == bob,
                    )
                )
            ).one()
            membership.role = Role.MODERATOR
            await db.commit()

    portal.call(make_bob_moderator)
    client.post("/api/v1/sessions", json={"email": BOB_EMAIL, "password": BOB_PASSWORD})

    assert client.delete(f"/api/v1/meetings/{SPRINT_12_MEETING_ID}").status_code == 204


def test_rename_is_stored_clears_generated_flag_and_is_audited(
    client: TestClient, sessionmaker: async_sessionmaker[AsyncSession], portal: BlockingPortal
) -> None:
    sign_in_as_alice(client)
    created = MeetingRead.model_validate_json(
        client.post(TEAM_MEETINGS, files={"file": ("call.wav", wav_bytes(), "audio/wav")}).text
    )
    assert created.name_is_generated is True

    response = client.patch(f"/api/v1/meetings/{created.id}", json={"name": "Planning"})

    assert response.status_code == 200
    assert response.json()["name"] == "Planning"
    assert response.json()["name_is_generated"] is False
    assert client.get(f"/api/v1/meetings/{created.id}").json()["name"] == "Planning"
    [event] = audit_events(sessionmaker, portal)
    assert event.action is AuditAction.MEETING_RENAMED
    assert event.meeting_id == created.id


def test_move_is_stored_and_audited_with_both_folders(
    client: TestClient, sessionmaker: async_sessionmaker[AsyncSession], portal: BlockingPortal
) -> None:
    sign_in_as_alice(client)
    meeting = f"/api/v1/meetings/{SPRINT_12_MEETING_ID}"

    response = client.patch(meeting, json={"folder_id": str(TEAM_DEFAULT_FOLDER_ID)})

    assert response.status_code == 200
    assert client.get(meeting).json()["folder_id"] == str(TEAM_DEFAULT_FOLDER_ID)
    [event] = audit_events(sessionmaker, portal)
    assert event.action is AuditAction.MEETING_MOVED
    assert event.details == {"from": str(SPRINT_FOLDER_ID), "to": str(TEAM_DEFAULT_FOLDER_ID)}


def test_move_to_another_workspaces_folder_is_422(
    client: TestClient, sessionmaker: async_sessionmaker[AsyncSession], portal: BlockingPortal
) -> None:
    sign_in_as_alice(client)
    meeting = f"/api/v1/meetings/{SPRINT_12_MEETING_ID}"

    response = client.patch(meeting, json={"folder_id": str(PERSONAL_FOLDER_ID)})

    assert response.status_code == 422
    assert client.get(meeting).json()["folder_id"] == str(SPRINT_FOLDER_ID)
    assert audit_events(sessionmaker, portal) == []


@pytest.mark.usefixtures("bob")
def test_plain_member_can_rename(client: TestClient) -> None:
    client.post("/api/v1/sessions", json={"email": BOB_EMAIL, "password": BOB_PASSWORD})

    response = client.patch(f"/api/v1/meetings/{SPRINT_12_MEETING_ID}", json={"name": "Bob's"})

    assert response.status_code == 200


def test_recorded_at_cannot_be_changed(client: TestClient) -> None:
    sign_in_as_alice(client)

    response = client.patch(
        f"/api/v1/meetings/{SPRINT_12_MEETING_ID}", json={"recorded_at": "2026-01-01T00:00:00Z"}
    )

    assert response.status_code == 422


SPRINT_12_TRANSCRIPT = f"/api/v1/meetings/{SPRINT_12_MEETING_ID}/transcript"


def test_transcript_comes_from_the_database(client: TestClient) -> None:
    sign_in_as_alice(client)

    body = TranscriptRead.model_validate_json(client.get(SPRINT_12_TRANSCRIPT).text)

    assert body.meeting_id == SPRINT_12_MEETING_ID
    assert body.language == "uk"
    assert body.revision.revision_type is RevisionType.ORIGINAL
    assert body.revision.is_current is True
    assert body.original_revision_id == body.revision.id
    assert body.is_edited is False
    assert [(s.display_name, s.is_unnamed) for s in body.speakers] == [
        ("Alice", False),
        ("Speaker 2", True),
    ]
    assert body.has_unnamed_speakers is True
    # In time order, each pointing at one of this revision's speakers.
    starts = [segment.start_seconds for segment in body.segments]
    assert len(starts) == 3
    assert starts == sorted(starts)
    speaker_ids = {speaker.id for speaker in body.speakers}
    assert {segment.speaker_id for segment in body.segments} <= speaker_ids


def test_meeting_without_transcript_is_409(client: TestClient) -> None:
    sign_in_as_alice(client)

    response = client.get(f"/api/v1/meetings/{DESIGN_SYNC_MEETING_ID}/transcript")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NOT_TRANSCRIBED"


def test_edited_revision_is_shown_and_the_original_stays_reachable(
    client: TestClient, sessionmaker: async_sessionmaker[AsyncSession], portal: BlockingPortal
) -> None:
    sign_in_as_alice(client)
    original_id = TranscriptRead.model_validate_json(
        client.get(SPRINT_12_TRANSCRIPT).text
    ).revision.id

    async def add_edited_revision() -> None:
        async with sessionmaker() as db:
            transcript = (
                await db.scalars(
                    select(Transcript).where(Transcript.meeting_id == SPRINT_12_MEETING_ID)
                )
            ).one()
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

    portal.call(add_edited_revision)
    body = TranscriptRead.model_validate_json(client.get(SPRINT_12_TRANSCRIPT).text)

    assert body.revision.revision_type is RevisionType.EDITED
    assert body.revision.edited_by_user_id == ALICE.id
    assert body.original_revision_id == original_id
    assert body.is_edited is True
    assert body.has_unnamed_speakers is False
    assert [segment.text for segment in body.segments] == ["Edited line."]
