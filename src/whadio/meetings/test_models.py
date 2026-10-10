from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError


@pytest.mark.slow
def test_folder_cannot_move_to_another_workspace(
    database_connection: Connection,
    folder_id: UUID,
    other_folder_id: UUID,
) -> None:
    # Arrange
    command = text(
        "UPDATE folder SET workspace_id = (SELECT workspace_id FROM folder "
        "WHERE folder_id = :other) WHERE folder_id = :folder"
    )
    # Act
    with pytest.raises(IntegrityError) as failure:
        database_connection.execute(command, {"other": other_folder_id, "folder": folder_id})
    # Assert
    assert "Folders cannot move between workspaces" in str(failure.value.orig)


@pytest.mark.slow
def test_meeting_cannot_move_to_another_workspace_folder(
    database_connection: Connection,
    meeting_id: UUID,
    other_folder_id: UUID,
) -> None:
    # Arrange
    command = text("UPDATE meeting SET folder_id = :folder WHERE meeting_id = :meeting")
    # Act
    with pytest.raises(IntegrityError) as failure:
        database_connection.execute(command, {"folder": other_folder_id, "meeting": meeting_id})
    # Assert
    assert "Meetings cannot move between workspaces" in str(failure.value.orig)


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


@pytest.mark.slow
@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO transcript_segment VALUES (:id, :revision, NULL, 0, 1, 'append')",
        "INSERT INTO speaker VALUES (:id, :revision, 'appended speaker')",
    ],
    ids=["segment", "speaker"],
)
def test_committed_original_rejects_appended_content(
    database_connection: Connection,
    committed_revision_id: UUID,
    statement: str,
) -> None:
    # Arrange
    command = text(statement)
    # Act
    with pytest.raises(IntegrityError) as failure:
        database_connection.execute(command, {"id": uuid4(), "revision": committed_revision_id})
    # Assert
    assert "Original content is immutable" in str(failure.value.orig)


@pytest.mark.slow
@pytest.mark.parametrize("table", ["transcript_segment", "speaker"])
def test_edited_content_cannot_be_moved_into_committed_original(
    database_connection: Connection,
    committed_revision_id: UUID,
    table: str,
) -> None:
    # Arrange
    edited = uuid4()
    content = uuid4()
    database_connection.execute(
        text(
            "INSERT INTO transcript_revision "
            "(revision_id, transcript_id, revision_type, created_at) "
            "SELECT :id, transcript_id, 'edited', now() FROM transcript_revision "
            "WHERE revision_id = :original"
        ),
        {"id": edited, "original": committed_revision_id},
    )
    if table == "speaker":
        database_connection.execute(
            text("INSERT INTO speaker VALUES (:id, :revision, 'edited')"),
            {"id": content, "revision": edited},
        )
        command = text("UPDATE speaker SET revision_id = :original WHERE speaker_id = :id")
    else:
        database_connection.execute(
            text("INSERT INTO transcript_segment VALUES (:id, :revision, NULL, 0, 1, 'edited')"),
            {"id": content, "revision": edited},
        )
        command = text(
            "UPDATE transcript_segment SET revision_id = :original WHERE segment_id = :id"
        )
    # Act
    with pytest.raises(IntegrityError) as failure:
        database_connection.execute(command, {"id": content, "original": committed_revision_id})
    # Assert
    assert "Original content is immutable" in str(failure.value.orig)


@pytest.mark.slow
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE speaker SET display_name = 'renamed' WHERE revision_id = :id",
        "DELETE FROM speaker WHERE revision_id = :id",
        "DELETE FROM transcript_segment WHERE revision_id = :id",
        (
            "UPDATE transcript_revision SET initialization_xid = pg_current_xact_id()::text "
            "WHERE revision_id = :id"
        ),
    ],
    ids=["rename-speaker", "delete-speaker", "delete-segment", "unseal-revision"],
)
def test_original_content_and_seal_cannot_be_changed(
    database_connection: Connection,
    committed_revision_id: UUID,
    statement: str,
) -> None:
    # Arrange
    command = text(statement)
    # Act
    with pytest.raises(IntegrityError) as failure:
        database_connection.execute(command, {"id": committed_revision_id})
    # Assert
    assert "immutable" in str(failure.value.orig)


@pytest.mark.slow
def test_initial_original_content_can_be_created_inside_savepoint(
    database_connection: Connection,
    revision_id: UUID,
) -> None:
    # Arrange
    speaker = uuid4()
    segment = uuid4()
    # Act
    with database_connection.begin_nested():
        database_connection.execute(
            text("INSERT INTO speaker VALUES (:id, :revision, 'initial speaker')"),
            {"id": speaker, "revision": revision_id},
        )
        database_connection.execute(
            text(
                "INSERT INTO transcript_segment VALUES (:id, :revision, :speaker, 0, 1, 'initial')"
            ),
            {"id": segment, "revision": revision_id, "speaker": speaker},
        )
    database_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    result = database_connection.execute(
        text(
            "SELECT s.text, p.display_name FROM transcript_segment s "
            "JOIN speaker p USING (speaker_id, revision_id) WHERE segment_id = :id"
        ),
        {"id": segment},
    ).one()
    # Assert
    assert tuple(result) == ("initial", "initial speaker")


@pytest.mark.slow
@pytest.mark.parametrize("operation", ["insert", "rename"])
def test_folder_names_are_unique_in_workspace_ignoring_case(
    database_connection: Connection,
    workspace_id: UUID,
    folder_id: UUID,
    operation: str,
) -> None:
    # Arrange
    database_connection.execute(
        text("UPDATE folder SET name = 'Planning' WHERE folder_id = :id"), {"id": folder_id}
    )
    if operation == "insert":
        command = text("INSERT INTO folder VALUES (:id, :workspace, 'planning', now(), false)")
        target = uuid4()
    else:
        command = text(
            "UPDATE folder SET name = 'planning' WHERE workspace_id = :workspace AND is_default"
        )
        target = folder_id
    # Act
    with pytest.raises(IntegrityError) as failure:
        database_connection.execute(command, {"id": target, "workspace": workspace_id})
    # Assert
    assert "uq_folder_workspace_name" in str(failure.value.orig)


@pytest.mark.slow
def test_folder_name_can_be_reused_in_another_workspace(
    database_connection: Connection,
    workspace_id: UUID,
    owner_id: UUID,
) -> None:
    # Arrange
    other = uuid4()
    database_connection.execute(
        text("INSERT INTO workspace VALUES (:id, 'other', 'summary', now(), false)"),
        {"id": other},
    )
    database_connection.execute(
        text("INSERT INTO workspace_membership VALUES (:id, :workspace, :user, 'Owner', now())"),
        {"id": uuid4(), "workspace": other, "user": owner_id},
    )
    # Act
    database_connection.execute(
        text("INSERT INTO folder VALUES (:id, :workspace, 'DEFAULT', now(), true)"),
        {"id": uuid4(), "workspace": other},
    )
    database_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    result = database_connection.execute(
        text("SELECT count(*) FROM folder WHERE workspace_id IN (:first, :second) AND is_default"),
        {"first": workspace_id, "second": other},
    ).one()
    # Assert
    assert tuple(result) == (2,)


@pytest.mark.slow
def test_deleting_folder_preserves_meeting_content_in_default_folder(
    database_connection: Connection,
    folder_id: UUID,
    meeting_id: UUID,
    revision_id: UUID,
) -> None:
    # Arrange
    database_connection.execute(
        text("UPDATE meeting SET storage_path = 'recording-key' WHERE meeting_id = :id"),
        {"id": meeting_id},
    )
    database_connection.execute(
        text("INSERT INTO transcript_segment VALUES (:id, :revision, NULL, 0, 1, 'original')"),
        {"id": uuid4(), "revision": revision_id},
    )
    database_connection.execute(
        text(
            "INSERT INTO note VALUES "
            "(:id, :meeting, 'summary', 'saved', 'test', 'Whadio', NULL, now())"
        ),
        {"id": uuid4(), "meeting": meeting_id},
    )
    # Act
    database_connection.execute(text("DELETE FROM folder WHERE folder_id = :id"), {"id": folder_id})
    database_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    result = database_connection.execute(
        text(
            "SELECT f.is_default, m.storage_path, s.text, n.content FROM meeting m "
            "JOIN folder f USING (folder_id) JOIN transcript t USING (meeting_id) "
            "JOIN transcript_revision r ON r.revision_id = t.current_revision_id "
            "JOIN transcript_segment s USING (revision_id) JOIN note n USING (meeting_id) "
            "WHERE m.meeting_id = :id"
        ),
        {"id": meeting_id},
    ).one()
    # Assert
    assert tuple(result) == (True, "recording-key", "original", "saved")


@pytest.mark.slow
def test_default_folder_cannot_be_deleted(
    database_connection: Connection,
    workspace_id: UUID,
) -> None:
    # Arrange
    command = text("DELETE FROM folder WHERE workspace_id = :id AND is_default")
    # Act
    with pytest.raises(IntegrityError) as failure:
        database_connection.execute(command, {"id": workspace_id})
    # Assert
    assert "Default folder cannot be deleted" in str(failure.value.orig)


@pytest.mark.slow
def test_workspace_deletion_still_cascades_through_original_content(
    database_connection: Connection,
    workspace_id: UUID,
    committed_revision_id: UUID,
) -> None:
    # Arrange
    command = text("DELETE FROM workspace WHERE workspace_id = :id")
    # Act
    database_connection.execute(command, {"id": workspace_id})
    database_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    result = database_connection.execute(
        text("SELECT count(*) FROM transcript_revision WHERE revision_id = :id"),
        {"id": committed_revision_id},
    ).one()
    # Assert
    assert tuple(result) == (0,)


@pytest.mark.slow
def test_original_initialization_transaction_cannot_be_spoofed(
    database_connection: Connection,
    revision_id: UUID,
) -> None:
    # Arrange
    edited = uuid4()
    # Act
    with database_connection.begin_nested():
        database_connection.execute(
            text(
                "INSERT INTO transcript_revision "
                "(revision_id, transcript_id, revision_type, created_at, initialization_xid) "
                "SELECT :id, transcript_id, 'edited', now(), 'spoofed' "
                "FROM transcript_revision WHERE revision_id = :original"
            ),
            {"id": edited, "original": revision_id},
        )
    result = database_connection.execute(
        text(
            "SELECT initialization_xid = pg_current_xact_id()::text "
            "FROM transcript_revision WHERE revision_id = :id"
        ),
        {"id": edited},
    ).one()
    # Assert
    assert tuple(result) == (True,)


@pytest.mark.slow
def test_edited_revision_cannot_be_relabelled_as_original(
    database_connection: Connection,
    revision_id: UUID,
) -> None:
    # Arrange
    edited = uuid4()
    database_connection.execute(
        text(
            "INSERT INTO transcript_revision "
            "(revision_id, transcript_id, revision_type, created_at) "
            "SELECT :id, transcript_id, 'edited', now() FROM transcript_revision "
            "WHERE revision_id = :original"
        ),
        {"id": edited, "original": revision_id},
    )
    # Act
    with pytest.raises(IntegrityError) as failure:
        database_connection.execute(
            text(
                "UPDATE transcript_revision SET revision_type = 'original' WHERE revision_id = :id"
            ),
            {"id": edited},
        )
    # Assert
    assert "Original revision is immutable" in str(failure.value.orig)


@pytest.mark.slow
def test_deleting_folder_keeps_restricted_meeting_grants(
    database_connection: Connection,
    folder_id: UUID,
    meeting_id: UUID,
    owner_id: UUID,
) -> None:
    # Arrange
    database_connection.execute(
        text("UPDATE meeting SET access_mode = 'restricted' WHERE meeting_id = :id"),
        {"id": meeting_id},
    )
    database_connection.execute(
        text("INSERT INTO meeting_access_grant VALUES (:id, :meeting, :user, :user, now())"),
        {"id": uuid4(), "meeting": meeting_id, "user": owner_id},
    )
    # Act
    database_connection.execute(text("DELETE FROM folder WHERE folder_id = :id"), {"id": folder_id})
    database_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    result = database_connection.execute(
        text(
            "SELECT m.access_mode, g.user_id FROM meeting m "
            "JOIN meeting_access_grant g USING (meeting_id) WHERE m.meeting_id = :id"
        ),
        {"id": meeting_id},
    ).one()
    # Assert
    assert tuple(result) == ("restricted", owner_id)


@pytest.mark.slow
def test_edited_content_remains_editable_without_changing_original(
    database_connection: Connection,
    committed_revision_id: UUID,
) -> None:
    # Arrange
    edited = uuid4()
    speaker = uuid4()
    database_connection.execute(
        text(
            "INSERT INTO transcript_revision "
            "(revision_id, transcript_id, revision_type, created_at) "
            "SELECT :id, transcript_id, 'edited', now() FROM transcript_revision "
            "WHERE revision_id = :original"
        ),
        {"id": edited, "original": committed_revision_id},
    )
    database_connection.execute(
        text("INSERT INTO speaker VALUES (:id, :revision, 'copied speaker')"),
        {"id": speaker, "revision": edited},
    )
    database_connection.execute(
        text("INSERT INTO transcript_segment VALUES (:id, :revision, :speaker, 0, 1, 'copied')"),
        {"id": uuid4(), "revision": edited, "speaker": speaker},
    )
    # Act
    database_connection.execute(
        text("UPDATE transcript_segment SET text = 'corrected' WHERE revision_id = :id"),
        {"id": edited},
    )
    database_connection.execute(
        text("UPDATE speaker SET display_name = 'renamed' WHERE revision_id = :id"),
        {"id": edited},
    )
    database_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    result = database_connection.execute(
        text(
            "SELECT r.revision_type, s.text, p.display_name FROM transcript_revision r "
            "JOIN transcript_segment s USING (revision_id) JOIN speaker p USING (revision_id) "
            "WHERE r.revision_id IN (:original, :edited) ORDER BY r.revision_type"
        ),
        {"original": committed_revision_id, "edited": edited},
    ).all()
    # Assert
    assert [tuple(row) for row in result] == [
        ("edited", "corrected", "renamed"),
        ("original", "original", "original speaker"),
    ]


@pytest.mark.slow
def test_folder_deletion_move_rolls_back_with_its_transaction(
    database_connection: Connection,
    folder_id: UUID,
    meeting_id: UUID,
) -> None:
    # Arrange
    savepoint = database_connection.begin_nested()
    # Act
    database_connection.execute(text("DELETE FROM folder WHERE folder_id = :id"), {"id": folder_id})
    savepoint.rollback()
    result = database_connection.execute(
        text("SELECT folder_id FROM meeting WHERE meeting_id = :id"), {"id": meeting_id}
    ).one()
    # Assert
    assert tuple(result) == (folder_id,)
