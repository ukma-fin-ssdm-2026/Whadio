from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..accounts.enums import WorkspaceRole
from ..accounts.models import User, WorkspaceMembership
from .models import ExternalShare, MeetingAccessGrant


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


@pytest.mark.slow
@pytest.mark.parametrize(
    "replacement", [False, True], ids=["without-replacement", "explicit-replacement"]
)
def test_last_recipient_removal_requires_explicit_replacement(
    database_session: Session,
    meeting_id: UUID,
    workspace_id: UUID,
    owner_id: UUID,
    *,
    replacement: bool,
) -> None:
    # Arrange
    database_connection = database_session.connection()
    departing = User(
        email=f"{uuid4()}@example.test",
        name="departing",
        password_hash=uuid4().hex,
        terms_accepted_at=datetime.now(UTC),
    )
    database_session.add(departing)
    database_session.flush()
    database_session.add(
        WorkspaceMembership(
            workspace_id=workspace_id, user_id=departing.user_id, role=WorkspaceRole.MEMBER
        )
    )
    database_session.add(
        MeetingAccessGrant(
            meeting_id=meeting_id, user_id=departing.user_id, granted_by_user_id=owner_id
        )
    )
    database_session.flush()
    database_connection.execute(
        text("UPDATE meeting SET access_mode = 'restricted' WHERE meeting_id = :id"),
        {"id": meeting_id},
    )
    if replacement:
        database_session.add(
            MeetingAccessGrant(meeting_id=meeting_id, user_id=owner_id, granted_by_user_id=owner_id)
        )
        database_session.flush()
    # Act
    database_connection.execute(
        text("DELETE FROM meeting_access_grant WHERE user_id = :id"), {"id": departing.user_id}
    )
    database_connection.execute(
        text("DELETE FROM workspace_membership WHERE workspace_id = :workspace AND user_id = :id"),
        {"workspace": workspace_id, "id": departing.user_id},
    )
    if replacement:
        database_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        result = database_connection.execute(
            text(
                "SELECT m.access_mode, g.user_id FROM meeting m "
                "JOIN meeting_access_grant g USING (meeting_id) WHERE m.meeting_id = :id"
            ),
            {"id": meeting_id},
        ).one()
        outcome = tuple(result) == ("restricted", owner_id)
    else:
        with pytest.raises(IntegrityError) as failure:
            database_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        outcome = "Restricted meeting requires an access grant" in str(failure.value.orig)
    # Assert
    assert outcome


@pytest.mark.slow
@pytest.mark.parametrize("redacted", [False, True])
def test_external_share_is_created_without_a_recording_option(
    database_session: Session, meeting_id: UUID, owner_id: UUID, *, redacted: bool
) -> None:
    # Arrange
    share = ExternalShare(
        meeting_id=meeting_id,
        created_by_user_id=owner_id,
        token_hash=uuid4().hex,
        redact_speaker_names=redacted,
    )
    # Act
    database_session.add(share)
    database_session.flush()
    database_session.refresh(share)
    # Assert
    assert share.redact_speaker_names == redacted
