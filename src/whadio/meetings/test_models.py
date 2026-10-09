from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError


@pytest.mark.slow
def test_transcript_and_current_revision_can_be_created_together(
    database_connection: Connection,
    revision_id: UUID,
) -> None:
    # Arrange
    command = text("SELECT count(*) FROM transcript WHERE current_revision_id = :id")
    # Act
    database_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    result = database_connection.execute(command, {"id": revision_id}).one()
    # Assert
    assert tuple(result) == (1,)


@pytest.mark.slow
def test_current_revision_must_belong_to_the_transcript(
    database_connection: Connection,
    revision_id: UUID,
) -> None:
    # Arrange
    database_connection.execute(
        text(
            "UPDATE transcript SET current_revision_id = :missing WHERE current_revision_id = :id"
        ),
        {"missing": uuid4(), "id": revision_id},
    )
    # Act
    with pytest.raises(IntegrityError) as failure:
        database_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    # Assert
    assert "fk_transcript_current_revision" in str(failure.value.orig)


@pytest.mark.slow
def test_original_revision_cannot_be_relabelled(
    database_connection: Connection,
    revision_id: UUID,
) -> None:
    # Arrange
    command = text(
        "UPDATE transcript_revision SET revision_type = 'edited' WHERE revision_id = :id"
    )
    # Act
    with pytest.raises(IntegrityError) as failure:
        database_connection.execute(command, {"id": revision_id})
    # Assert
    assert "Original revision is immutable" in str(failure.value.orig)


@pytest.mark.slow
def test_original_segment_cannot_be_overwritten(
    database_connection: Connection,
    revision_id: UUID,
) -> None:
    # Arrange
    segment = uuid4()
    database_connection.execute(
        text("INSERT INTO transcript_segment VALUES (:id, :revision, NULL, 0, 1, 'original')"),
        {"id": segment, "revision": revision_id},
    )
    # Act
    with pytest.raises(IntegrityError) as failure:
        database_connection.execute(
            text("UPDATE transcript_segment SET text = 'edit' WHERE segment_id = :id"),
            {"id": segment},
        )
    # Assert
    assert "Original content is immutable" in str(failure.value.orig)


@pytest.mark.slow
def test_meeting_deletion_cascades_through_original_transcript(
    database_connection: Connection,
    meeting_id: UUID,
    revision_id: UUID,
) -> None:
    # Arrange
    database_connection.execute(
        text("INSERT INTO transcript_segment VALUES (:id, :revision, NULL, 0, 1, 'original')"),
        {"id": uuid4(), "revision": revision_id},
    )
    # Act
    database_connection.execute(
        text("DELETE FROM meeting WHERE meeting_id = :id"), {"id": meeting_id}
    )
    database_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    result = database_connection.execute(
        text("SELECT count(*) FROM transcript_revision WHERE revision_id = :id"),
        {"id": revision_id},
    ).one()
    # Assert
    assert tuple(result) == (0,)


@pytest.mark.slow
def test_segment_end_must_be_after_start(
    database_connection: Connection,
    revision_id: UUID,
) -> None:
    # Arrange
    command = text("INSERT INTO transcript_segment VALUES (:id, :revision, NULL, 1, 1, 'test')")
    # Act
    with pytest.raises(IntegrityError) as failure:
        database_connection.execute(command, {"id": uuid4(), "revision": revision_id})
    # Assert
    assert "time_interval" in str(failure.value.orig)


@pytest.mark.slow
def test_context_snapshot_survives_source_meeting_deletion(
    database_connection: Connection,
    meeting_id: UUID,
    folder_id: UUID,
    owner_id: UUID,
) -> None:
    # Arrange
    other_meeting = uuid4()
    note = uuid4()
    context = uuid4()
    database_connection.execute(
        text("""
        INSERT INTO meeting (
            meeting_id, folder_id, created_by_user_id, name, name_is_generated,
            source_type, recording_status, processing_state, recorded_at, created_at,
            recording_delete_after, access_mode
        ) VALUES (:id, :folder, :user, 'test', false, 'upload', 'complete', 'processed',
                  now(), now(), now() + interval '90 days', 'workspace')
    """),
        {"id": other_meeting, "folder": folder_id, "user": owner_id},
    )
    database_connection.execute(
        text(
            "INSERT INTO note VALUES "
            "(:id, :meeting, 'summary', 'saved', 'test', 'Whadio', NULL, now())"
        ),
        {"id": note, "meeting": other_meeting},
    )
    database_connection.execute(
        text("INSERT INTO note_context_meeting VALUES (:id, :note, :meeting, 'saved name')"),
        {"id": context, "note": note, "meeting": meeting_id},
    )
    # Act
    database_connection.execute(
        text("DELETE FROM meeting WHERE meeting_id = :id"), {"id": meeting_id}
    )
    result = database_connection.execute(
        text(
            "SELECT context_meeting_id, context_meeting_name_snapshot "
            "FROM note_context_meeting WHERE note_context_meeting_id = :id"
        ),
        {"id": context},
    ).one()
    # Assert
    assert tuple(result) == (None, "saved name")
