from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .enums import InvitationRole, InvitationStatus, WorkspaceRole
from .models import Invitation, WorkspaceMembership


@pytest.mark.slow
def test_membership_role_round_trips_as_enum(
    database_session: Session,
    workspace_id: UUID,
) -> None:
    # Arrange
    query = select(WorkspaceMembership.role).where(WorkspaceMembership.workspace_id == workspace_id)
    # Act
    role = database_session.scalars(query).one()
    # Assert
    assert role is WorkspaceRole.OWNER


@pytest.mark.slow
def test_workspace_owner_and_default_folder_can_be_created_together(
    database_connection: Connection,
    workspace_id: UUID,
) -> None:
    # Arrange
    command = text("SELECT count(*) FROM workspace WHERE workspace_id = :id")
    # Act
    database_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    result = database_connection.execute(command, {"id": workspace_id}).one()
    # Assert
    assert tuple(result) == (1,)


@pytest.mark.slow
def test_workspace_cannot_lose_its_default_folder(
    database_connection: Connection,
    workspace_id: UUID,
) -> None:
    # Arrange
    database_connection.execute(
        text("UPDATE folder SET is_default = false WHERE workspace_id = :id"),
        {"id": workspace_id},
    )
    # Act
    with pytest.raises(IntegrityError) as failure:
        database_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    # Assert
    assert "exactly one default folder" in str(failure.value.orig)


@pytest.mark.slow
def test_workspace_cannot_lose_its_owner(
    database_connection: Connection,
    workspace_id: UUID,
) -> None:
    # Arrange
    database_connection.execute(
        text("DELETE FROM workspace_membership WHERE workspace_id = :id"), {"id": workspace_id}
    )
    # Act
    with pytest.raises(IntegrityError) as failure:
        database_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    # Assert
    assert "exactly one Owner" in str(failure.value.orig)


@pytest.mark.slow
def test_workspace_cannot_have_two_owners(
    database_connection: Connection,
    workspace_id: UUID,
) -> None:
    # Arrange
    user = uuid4()
    database_connection.execute(
        text("INSERT INTO \"user\" VALUES (:id, :email, 'test', 'hash', false, now(), now())"),
        {"id": user, "email": f"{user}@example.test"},
    )
    # Act
    with pytest.raises(IntegrityError) as failure:
        database_connection.execute(
            text(
                "INSERT INTO workspace_membership VALUES (:id, :workspace, :user, 'Owner', now())"
            ),
            {"id": uuid4(), "workspace": workspace_id, "user": user},
        )
    # Assert
    assert "uq_workspace_owner" in str(failure.value.orig)


@pytest.mark.slow
def test_personal_workspace_rejects_invitation(
    database_connection: Connection,
    database_session: Session,
    workspace_id: UUID,
    owner_id: UUID,
) -> None:
    # Arrange
    database_connection.execute(
        text("UPDATE workspace SET is_personal = true WHERE workspace_id = :id"),
        {"id": workspace_id},
    )
    now = datetime.now(UTC)
    database_session.add(
        Invitation(
            workspace_id=workspace_id,
            invited_email="invitee@example.test",
            role=InvitationRole.MEMBER,
            invited_by_user_id=owner_id,
            status=InvitationStatus.PENDING,
            token_hash=str(uuid4()),
            created_at=now,
            expires_at=now + timedelta(days=7),
        )
    )
    # Act
    with pytest.raises(IntegrityError) as failure:
        database_session.flush()
    # Assert
    assert "Personal workspace cannot have invitations" in str(failure.value.orig)
