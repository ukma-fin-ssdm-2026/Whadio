from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ...accounts.enums import WorkspaceRole
from ...accounts.models import Workspace, WorkspaceMembership
from ...meetings.models import Folder, RecordingDeletion
from ...shared.notes_llm import AnthropicLlm, NotesLlm, OllamaLlm
from ..core.errors import ErrorResponse
from ..core.schemas import Page
from .schemas import Provider, WorkspaceRead, WorkspaceSummary

pytestmark = pytest.mark.slow

PASSWORD = uuid4().hex
CONFIGURED_PROVIDERS = [
    (OllamaLlm(provider="ollama", model="gemma4:12b-it-qat"), Provider.WHADIO),
    (AnthropicLlm(), Provider.ANTHROPIC),
]


async def signed_in(client: AsyncClient, session: AsyncSession) -> UUID:
    user = await AsyncDatabase.add_account(session, PASSWORD)
    await client.post("/api/v1/sessions", json={"email": user.email, "password": PASSWORD})
    return user.user_id


async def created(client: AsyncClient, name: str = "Product team") -> WorkspaceRead:
    response = await client.post("/api/v1/workspaces", json={"name": name})
    return WorkspaceRead.model_validate_json(response.content)


def error_code(response: Response) -> str:
    return ErrorResponse.model_validate_json(response.content).error.code


def test_created_workspace_is_owned_by_its_creator(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str, str]:
        async with AsyncDatabase.api_client(session) as client:
            await signed_in(client, session)
            # Act
            response = await client.post("/api/v1/workspaces", json={"name": "Product team"})
            workspace = WorkspaceRead.model_validate_json(response.content)
            return response.status_code, workspace.my_role, response.headers["Location"]

    status, role, location = async_database.run(scenario)
    # Assert
    assert (status, role, location.startswith("https://example.test/api/v1/workspaces/")) == (
        201,
        "owner",
        True,
    )


def test_created_workspace_is_listed(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[UUID, str]:
        async with AsyncDatabase.api_client(session) as client:
            await signed_in(client, session)
            workspace = await created(client)
            # Act
            response = await client.get("/api/v1/workspaces")
            return workspace.id, response.text

    workspace_id, listed = async_database.run(scenario)
    # Assert
    assert str(workspace_id) in listed


@pytest.mark.parametrize(("llm", "provider"), CONFIGURED_PROVIDERS)
def test_workspace_list_reports_the_configured_provider(
    async_database: AsyncDatabase, llm: NotesLlm, provider: Provider
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> set[Provider]:
        async with AsyncDatabase.api_client(session, llm) as client:
            await signed_in(client, session)
            await created(client)
            # Act
            response = await client.get("/api/v1/workspaces")
            page = Page[WorkspaceSummary].model_validate_json(response.content)
            return {item.notes_provider for item in page.items}

    reported = async_database.run(scenario)
    # Assert
    assert reported == {provider}


@pytest.mark.parametrize(("llm", "provider"), CONFIGURED_PROVIDERS)
def test_workspace_detail_reports_the_configured_provider(
    async_database: AsyncDatabase, llm: NotesLlm, provider: Provider
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Provider:
        async with AsyncDatabase.api_client(session, llm) as client:
            await signed_in(client, session)
            workspace = await created(client)
            # Act
            response = await client.get(f"/api/v1/workspaces/{workspace.id}")
            return WorkspaceRead.model_validate_json(response.content).notes_provider

    reported = async_database.run(scenario)
    # Assert
    assert reported is provider


def test_workspace_detail_reports_the_configured_model(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> str:
        async with AsyncDatabase.api_client(session, AnthropicLlm(model="claude-test")) as client:
            await signed_in(client, session)
            workspace = await created(client)
            # Act
            response = await client.get(f"/api/v1/workspaces/{workspace.id}")
            return WorkspaceRead.model_validate_json(response.content).notes_model

    model = async_database.run(scenario)
    # Assert
    assert model == "claude-test"


def test_workspace_list_leaves_the_model_out(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> str:
        async with AsyncDatabase.api_client(session) as client:
            await signed_in(client, session)
            await created(client)
            # Act
            response = await client.get("/api/v1/workspaces")
            return response.text

    listed = async_database.run(scenario)
    # Assert
    assert "notes_model" not in listed


def test_workspace_of_others_is_not_found(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str]:
        async with AsyncDatabase.api_client(session) as client:
            await signed_in(client, session)
            # Act
            response = await client.get(f"/api/v1/workspaces/{uuid4()}")
            return response.status_code, error_code(response)

    found = async_database.run(scenario)
    # Assert
    assert found == (404, "NOT_FOUND")


def test_owner_changes_the_default_preset(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> str:
        async with AsyncDatabase.api_client(session) as client:
            await signed_in(client, session)
            workspace = await created(client)
            # Act
            response = await client.patch(
                f"/api/v1/workspaces/{workspace.id}", json={"default_preset": "interview"}
            )
            return WorkspaceRead.model_validate_json(response.content).default_preset

    preset = async_database.run(scenario)
    # Assert
    assert preset == "interview"


def test_member_cannot_change_settings(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str]:
        async with AsyncDatabase.api_client(session) as client:
            owner, _ = await AsyncDatabase.add_workspace(session)
            workspace_id = await session.scalar(
                select(WorkspaceMembership.workspace_id).where(WorkspaceMembership.user_id == owner)
            )
            member = await signed_in(client, session)
            session.add(
                WorkspaceMembership(
                    workspace_id=workspace_id, user_id=member, role=WorkspaceRole.MEMBER
                )
            )
            await session.flush()
            # Act
            response = await client.patch(
                f"/api/v1/workspaces/{workspace_id}", json={"name": "Mine now"}
            )
            return response.status_code, error_code(response)

    found = async_database.run(scenario)
    # Assert
    assert found == (403, "INSUFFICIENT_ROLE")


def test_update_without_a_field_is_a_validation_error(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str]:
        async with AsyncDatabase.api_client(session) as client:
            await signed_in(client, session)
            workspace = await created(client)
            # Act
            response = await client.patch(f"/api/v1/workspaces/{workspace.id}", json={})
            return response.status_code, error_code(response)

    found = async_database.run(scenario)
    # Assert
    assert found == (422, "VALIDATION_ERROR")


def test_deleted_workspace_is_gone(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, int]:
        async with AsyncDatabase.api_client(session) as client:
            await signed_in(client, session)
            workspace = await created(client)
            # Act
            deleted = await client.delete(f"/api/v1/workspaces/{workspace.id}")
            found = await client.get(f"/api/v1/workspaces/{workspace.id}")
            return deleted.status_code, found.status_code

    found = async_database.run(scenario)
    # Assert
    assert found == (204, 404)


def test_personal_workspace_cannot_be_deleted(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str]:
        async with AsyncDatabase.api_client(session) as client:
            await signed_in(client, session)
            workspace = await created(client, "Alice")
            stored = await session.get(Workspace, workspace.id)
            assert stored is not None
            stored.is_personal = True
            await session.flush()
            # Act
            response = await client.delete(f"/api/v1/workspaces/{workspace.id}")
            return response.status_code, error_code(response)

    found = async_database.run(scenario)
    # Assert
    assert found == (409, "PERSONAL_WORKSPACE")


def test_created_workspace_passes_the_database_guards(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int | None:
        async with AsyncDatabase.api_client(session) as client:
            await signed_in(client, session)
            # Act
            workspace = await created(client)
            # The guards (one Owner, one default folder) are deferred to a commit, which this
            # test rolls back instead.
            await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            return await session.scalar(
                select(func.count())
                .select_from(Folder)
                .where(Folder.workspace_id == workspace.id, Folder.is_default)
            )

    folders = async_database.run(scenario)
    # Assert
    assert folders == 1


def test_deleted_workspace_queues_its_recordings_for_deletion(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, bool]:
        async with AsyncDatabase.api_client(session) as client:
            await signed_in(client, session)
            workspace = await created(client)
            folder = await session.scalar(
                select(Folder.folder_id).where(Folder.workspace_id == workspace.id)
            )
            assert folder is not None
            owner = await session.scalar(
                select(WorkspaceMembership.user_id).where(
                    WorkspaceMembership.workspace_id == workspace.id
                )
            )
            assert owner is not None
            meeting_id = await AsyncDatabase.add_meeting(session, (owner, folder))
            # Act
            response = await client.delete(f"/api/v1/workspaces/{workspace.id}")
            await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            queued = await session.scalars(select(RecordingDeletion.storage_key))
            return response.status_code, f"meetings/{meeting_id}" in queued.all()

    found = async_database.run(scenario)
    # Assert
    assert found == (204, True)


def test_workspaces_need_a_session(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        async with AsyncDatabase.api_client(session) as client:
            # Act
            response = await client.get("/api/v1/workspaces")
            return response.status_code

    status = async_database.run(scenario)
    # Assert
    assert status == 401
