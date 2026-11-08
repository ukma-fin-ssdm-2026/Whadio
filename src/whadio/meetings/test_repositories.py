import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ..access_policy.contracts import MeetingScope
from .enums import AccessMode
from .models import Folder
from .repositories import MeetingRepository

pytestmark = pytest.mark.slow


def test_locked_scopes_are_the_workspaces_meetings_in_id_order(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[list[MeetingScope], list[MeetingScope]]:
        owner, folder_id = await AsyncDatabase.add_workspace(session)
        folder = await session.get(Folder, folder_id)
        assert folder is not None
        restricted = await AsyncDatabase.add_meeting(
            session, (owner, folder_id), access_mode=AccessMode.RESTRICTED
        )
        open_meeting = await AsyncDatabase.add_meeting(session, (owner, folder_id))
        elsewhere = await AsyncDatabase.add_meeting(
            session, await AsyncDatabase.add_workspace(session)
        )
        expected = sorted(
            [
                MeetingScope(restricted, folder.workspace_id, owner, restricted=True),
                MeetingScope(open_meeting, folder.workspace_id, owner, restricted=False),
            ],
            key=lambda scope: scope.meeting_id,
        )
        # Act
        found = await MeetingRepository(session).lock_scopes(
            folder.workspace_id, [elsewhere, open_meeting, restricted]
        )
        return found, expected

    found, expected = async_database.run(scenario)

    # Assert
    assert found == expected
