from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError


@pytest.mark.slow
def test_restricted_meeting_requires_at_least_one_grant(
    database_connection: Connection,
    meeting_id: UUID,
) -> None:
    # Arrange
    database_connection.execute(
        text("UPDATE meeting SET access_mode = 'restricted' WHERE meeting_id = :id"),
        {"id": meeting_id},
    )
    # Act
    with pytest.raises(IntegrityError) as failure:
        database_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    # Assert
    assert "requires an access grant" in str(failure.value.orig)


@pytest.mark.slow
def test_restriction_and_member_grant_can_be_created_together(
    database_connection: Connection,
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
    database_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    result = database_connection.execute(
        text("SELECT access_mode FROM meeting WHERE meeting_id = :id"), {"id": meeting_id}
    ).one()
    # Assert
    assert tuple(result) == ("restricted",)


@pytest.mark.slow
def test_access_grant_rejects_nonmember(
    database_connection: Connection,
    meeting_id: UUID,
    owner_id: UUID,
) -> None:
    # Arrange
    stranger = uuid4()
    database_connection.execute(
        text("INSERT INTO \"user\" VALUES (:id, :email, 'test', 'hash', false, now(), now())"),
        {"id": stranger, "email": f"{stranger}@example.test"},
    )
    database_connection.execute(
        text("INSERT INTO meeting_access_grant VALUES (:id, :meeting, :user, :actor, now())"),
        {"id": uuid4(), "meeting": meeting_id, "user": stranger, "actor": owner_id},
    )
    # Act
    with pytest.raises(IntegrityError) as failure:
        database_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    # Assert
    assert "requires workspace membership" in str(failure.value.orig)
