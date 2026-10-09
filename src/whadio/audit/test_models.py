from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, text


@pytest.mark.slow
def test_audit_event_survives_workspace_deletion(
    database_connection: Connection,
    workspace_id: UUID,
    meeting_id: UUID,
    owner_id: UUID,
) -> None:
    # Arrange
    event = uuid4()
    database_connection.execute(
        text(
            "INSERT INTO audit_event VALUES "
            "(:id, now(), :actor, 'meeting_deleted', :workspace, :meeting, NULL, NULL)"
        ),
        {"id": event, "actor": owner_id, "workspace": workspace_id, "meeting": meeting_id},
    )
    # Act
    database_connection.execute(
        text("DELETE FROM workspace WHERE workspace_id = :id"), {"id": workspace_id}
    )
    database_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    result = database_connection.execute(
        text("SELECT count(*) FROM audit_event WHERE audit_event_id = :id"), {"id": event}
    ).one()
    # Assert
    assert tuple(result) == (1,)


@pytest.mark.slow
def test_audit_event_rolls_back_with_business_change(
    database_connection: Connection,
    workspace_id: UUID,
    owner_id: UUID,
) -> None:
    # Arrange
    event = uuid4()
    savepoint = database_connection.begin_nested()
    database_connection.execute(
        text(
            "INSERT INTO audit_event VALUES "
            "(:id, now(), :actor, 'workspace_deleted', :workspace, NULL, NULL, NULL)"
        ),
        {"id": event, "actor": owner_id, "workspace": workspace_id},
    )
    database_connection.execute(
        text("DELETE FROM workspace WHERE workspace_id = :id"), {"id": workspace_id}
    )
    # Act
    savepoint.rollback()
    result = database_connection.execute(
        text(
            "SELECT EXISTS(SELECT 1 FROM workspace WHERE workspace_id = :workspace), "
            "EXISTS(SELECT 1 FROM audit_event WHERE audit_event_id = :event)"
        ),
        {"workspace": workspace_id, "event": event},
    ).one()
    # Assert
    assert tuple(result) == (True, False)
