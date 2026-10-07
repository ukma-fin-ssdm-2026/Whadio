from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.accounts.fixtures import (
    ALICE,
    DEMO_EMAIL,
    DEMO_PASSWORD,
    PERSONAL_WORKSPACE_ID,
    TEAM_WORKSPACE_ID,
)
from api.audit.models import AuditAction, AuditEvent
from conftest import BOB_EMAIL, BOB_PASSWORD

WORKSPACES = "/api/v1/workspaces"
TEAM = f"{WORKSPACES}/{TEAM_WORKSPACE_ID}"
PERSONAL = f"{WORKSPACES}/{PERSONAL_WORKSPACE_ID}"


def sign_in_as_alice(client: TestClient) -> None:
    client.post("/api/v1/sessions", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})


def sign_in_as_bob(client: TestClient) -> None:
    client.post("/api/v1/sessions", json={"email": BOB_EMAIL, "password": BOB_PASSWORD})


def test_list_shows_my_workspaces_oldest_first(client: TestClient) -> None:
    sign_in_as_alice(client)

    items = client.get(WORKSPACES).json()["items"]

    assert [item["id"] for item in items] == [str(PERSONAL_WORKSPACE_ID), str(TEAM_WORKSPACE_ID)]
    assert items[0]["is_personal"] is True
    assert items[0]["my_role"] == "owner"


def test_list_needs_sign_in(client: TestClient) -> None:
    assert client.get(WORKSPACES).status_code == 401


def test_create_makes_me_owner_and_is_stored(client: TestClient) -> None:
    sign_in_as_alice(client)

    response = client.post(WORKSPACES, json={"name": "Research"})

    assert response.status_code == 201
    created = response.json()
    assert created["name"] == "Research"
    assert created["my_role"] == "owner"
    assert created["member_count"] == 1
    assert created["is_personal"] is False
    assert created["default_preset"] == "summary"
    assert response.headers["Location"].endswith(f"{WORKSPACES}/{created['id']}")
    # Stored: it comes back from a fresh read and is last in the list, being the newest.
    assert client.get(f"{WORKSPACES}/{created['id']}").json() == created
    assert client.get(WORKSPACES).json()["items"][-1]["id"] == created["id"]


def test_member_sees_their_role_and_the_member_count(client: TestClient, bob: UUID) -> None:
    sign_in_as_bob(client)

    team = client.get(TEAM).json()

    assert team["my_role"] == "member"
    assert team["member_count"] == 2
    # The team workspace is older than Bob's account, so it comes before his personal one.
    team_item, personal = client.get(WORKSPACES).json()["items"]
    assert team_item["id"] == str(TEAM_WORKSPACE_ID)
    assert personal["is_personal"] is True
    assert personal["my_role"] == "owner"
    assert personal["name"] == "Bob Member"
    assert personal["member_count"] == 1


def test_non_member_gets_404_not_403(client: TestClient, bob: UUID) -> None:
    sign_in_as_bob(client)

    for response in (
        client.get(PERSONAL),
        client.patch(PERSONAL, json={"name": "Mine now"}),
        client.delete(PERSONAL),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"


def test_unknown_workspace_is_404(client: TestClient) -> None:
    sign_in_as_alice(client)

    assert client.get(f"{WORKSPACES}/00000000-0000-4000-8000-000000000000").status_code == 404


def test_owner_updates_and_the_change_is_stored(client: TestClient) -> None:
    sign_in_as_alice(client)

    response = client.patch(TEAM, json={"name": "Renamed team", "default_preset": "interview"})

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed team"
    stored = client.get(TEAM).json()
    assert stored["name"] == "Renamed team"
    assert stored["default_preset"] == "interview"


def test_update_with_only_one_field_keeps_the_other(client: TestClient) -> None:
    sign_in_as_alice(client)
    before = client.get(TEAM).json()

    client.patch(TEAM, json={"default_preset": "summary"})

    assert client.get(TEAM).json()["name"] == before["name"]


def test_member_cannot_update_or_delete(client: TestClient, bob: UUID) -> None:
    sign_in_as_bob(client)

    for response in (client.patch(TEAM, json={"name": "Bob's now"}), client.delete(TEAM)):
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "INSUFFICIENT_ROLE"
    assert client.get(TEAM).json()["name"] == "Whadio team"


def test_personal_workspace_cannot_be_deleted(client: TestClient) -> None:
    sign_in_as_alice(client)

    response = client.delete(PERSONAL)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PERSONAL_WORKSPACE"
    assert client.get(PERSONAL).status_code == 200


def test_owner_deletes_and_it_is_audited(client: TestClient, bob: UUID) -> None:
    sign_in_as_alice(client)

    assert client.delete(TEAM).status_code == 204

    assert client.get(TEAM).status_code == 404
    assert str(TEAM_WORKSPACE_ID) not in [i["id"] for i in client.get(WORKSPACES).json()["items"]]

    async def audit_events() -> list[AuditEvent]:
        async with client.app.state.sessionmaker() as db:
            return [*await db.scalars(select(AuditEvent))]

    events = client.portal.call(audit_events)
    assert len(events) == 1
    assert events[0].action is AuditAction.WORKSPACE_DELETED
    assert events[0].workspace_id == TEAM_WORKSPACE_ID
    assert events[0].actor_user_id == ALICE.id
    assert events[0].meeting_id is None


def test_deleting_removes_other_members_too(client: TestClient, bob: UUID) -> None:
    sign_in_as_alice(client)
    client.delete(TEAM)
    client.cookies.clear()

    sign_in_as_bob(client)

    items = client.get(WORKSPACES).json()["items"]
    assert [item["is_personal"] for item in items] == [True]
