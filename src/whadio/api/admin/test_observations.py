import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ...admin.services import ObservationStore
from ...admin.settings import AdminSettings, SourceSettings
from ..app import create_app
from ..composition import observation_store


def receiver_fixture() -> tuple[TestClient, str]:
    token = uuid4().hex
    store = ObservationStore(
        AdminSettings(
            sources={
                "main-host": SourceSettings(
                    token_hash=hashlib.sha256(token.encode()).hexdigest(), kind="host"
                )
            }
        )
    )
    app = create_app()
    app.dependency_overrides[observation_store] = lambda: store
    return TestClient(app), token


def test_private_receiver_accepts_valid_source_without_browser_session() -> None:
    # Arrange
    client, token = receiver_fixture()
    # Act
    response = client.post(
        "/api/v1/admin/observations/main-host",
        headers={"Authorization": f"Bearer {token}"},
        json={"sampled_at": datetime.now(UTC).isoformat(), "kind": "host", "cpu_percent": 0},
    )
    # Assert
    assert (response.status_code, response.content) == (204, b"")


@pytest.mark.parametrize("source", ["main-host", "other-host"])
def test_private_receiver_rejects_unknown_or_wrong_source_credentials(source: str) -> None:
    # Arrange
    client, _ = receiver_fixture()
    # Act
    response = client.post(
        f"/api/v1/admin/observations/{source}",
        headers={"Authorization": f"Bearer {uuid4().hex}"},
        json={"sampled_at": datetime.now(UTC).isoformat(), "kind": "host"},
    )
    # Assert
    assert response.status_code == 401


def test_receiver_rejects_replayed_observation() -> None:
    # Arrange
    client, token = receiver_fixture()
    payload = {"sampled_at": datetime.now(UTC).isoformat(), "kind": "host"}
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/api/v1/admin/observations/main-host", headers=headers, json=payload)
    # Act
    response = client.post("/api/v1/admin/observations/main-host", headers=headers, json=payload)
    # Assert
    assert (response.status_code, response.json()["error"]["code"]) == (409, "STALE_OBSERVATION")


def test_receiver_caps_the_body_before_json_validation() -> None:
    # Arrange
    client, token = receiver_fixture()
    # Act
    response = client.post(
        "/api/v1/admin/observations/main-host",
        headers={"Authorization": f"Bearer {token}"},
        content=b"x" * 16385,
    )
    # Assert
    assert response.status_code == 413


def test_receiver_does_not_echo_invalid_body_values() -> None:
    # Arrange
    client, token = receiver_fixture()
    marker = uuid4().hex
    # Act
    response = client.post(
        "/api/v1/admin/observations/main-host",
        headers={"Authorization": f"Bearer {token}"},
        json={"sampled_at": datetime.now(UTC).isoformat(), "kind": "host", "cpu_percent": marker},
    )
    # Assert
    assert (response.status_code, marker in response.text) == (422, False)


@pytest.mark.parametrize("endpoint", ["jobs", "metrics"])
def test_admin_reads_require_a_browser_session(endpoint: str) -> None:
    # Arrange
    client = TestClient(create_app())
    # Act
    response = client.get(f"/api/v1/admin/{endpoint}")
    # Assert
    assert response.status_code == 401
