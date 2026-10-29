import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from ..accounts.models import PendingRegistration, User, Workspace, WorkspaceMembership
from ..accounts.repositories import RegistrationRepository, SessionRepository
from ..accounts.services import RegistrationDetails, RegistrationIssuer
from ..shared.database import Database, DatabaseSettings
from ..shared.errors import UseCaseError
from .composition import registration_service

pytestmark = pytest.mark.slow
DETAILS = RegistrationDetails("Alice", f"A1{uuid4().hex}", accept_terms=True)


def test_concurrent_redemption_has_one_winner(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> list[str]:
        database = Database(database_settings)
        email = f"{uuid4()}@example.com"
        try:
            async with database.transaction() as session:
                link = await RegistrationIssuer(
                    RegistrationRepository(session), SessionRepository(session)
                ).issue(email, datetime.now(UTC))

            async def redeem() -> str:
                try:
                    async with database.transaction() as session:
                        await registration_service(session).complete(
                            link.registration_id, link.token, DETAILS, datetime.now(UTC)
                        )
                except UseCaseError as error:
                    return error.code.value
                return "created"

            # Act
            return sorted(await asyncio.gather(redeem(), redeem()))
        finally:
            async with database.transaction() as session:
                users = select(User.user_id).where(User.email == email)
                workspaces = select(WorkspaceMembership.workspace_id).where(
                    WorkspaceMembership.user_id.in_(users)
                )
                await session.execute(
                    delete(Workspace).where(Workspace.workspace_id.in_(workspaces))
                )
                await session.execute(delete(User).where(User.email == email))
                await session.execute(
                    delete(PendingRegistration).where(PendingRegistration.email == email)
                )
            await database.close()

    # Assert
    assert asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop) == [
        "LINK_INVALID",
        "created",
    ]
