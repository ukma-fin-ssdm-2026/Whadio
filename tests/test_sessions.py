from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.accounts.auth import SESSION_COOKIE
from api.accounts.fixtures import DEMO_EMAIL, DEMO_PASSWORD, TEAM_WORKSPACE_ID
from api.app import create_app

SESSIONS = "/api/v1/sessions"
SIGN_OUT = "/api/v1/sessions/current"
# Any endpoint behind the browser session will do.
WORKSPACES = "/api/v1/workspaces"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    # https, because the session cookie is Secure and is not sent over plain http.
    with TestClient(app, base_url="https://testserver") as client:
        yield client


def sign_in(client: TestClient, **overrides: str):
    return client.post(SESSIONS, json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD, **overrides})


def test_browser_sign_in_sets_cookie_that_authenticates(client: TestClient) -> None:
    response = sign_in(client)

    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "browser"
    assert body["user"]["email"] == DEMO_EMAIL
    assert body["token"] is None
    assert client.cookies.get(SESSION_COOKIE)
    assert client.get(WORKSPACES).status_code == 200


def test_email_is_matched_case_insensitively(client: TestClient) -> None:
    assert sign_in(client, email=DEMO_EMAIL.upper()).status_code == 201


@pytest.mark.parametrize(
    "credentials",
    [{"password": "wrong-password"}, {"email": "nobody@whadio.dev"}],
    ids=["wrong password", "unknown email"],
)
def test_bad_credentials_get_the_same_401(client: TestClient, credentials: dict[str, str]) -> None:
    response = sign_in(client, **credentials)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert SESSION_COOKIE not in client.cookies


def test_each_sign_in_gets_a_new_token(client: TestClient) -> None:
    sign_in(client)
    first = client.cookies.get(SESSION_COOKIE)
    client.cookies.clear()
    sign_in(client)

    assert client.cookies.get(SESSION_COOKIE) != first


def test_no_or_unknown_cookie_is_401(client: TestClient) -> None:
    assert client.get(WORKSPACES).status_code == 401

    client.cookies.set(SESSION_COOKIE, "not-a-real-token")
    response = client.get(WORKSPACES)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_sign_out_ends_the_session(client: TestClient) -> None:
    sign_in(client)
    token = client.cookies.get(SESSION_COOKIE)

    assert client.delete(SIGN_OUT).status_code == 204

    # Replaying the old cookie must not work: the session row is gone, not just the cookie.
    client.cookies.set(SESSION_COOKIE, token)
    assert client.get(WORKSPACES).status_code == 401


def test_sign_out_without_session_is_204(client: TestClient) -> None:
    assert client.delete(SIGN_OUT).status_code == 204


def test_extension_sign_in_returns_token_and_no_cookie(client: TestClient) -> None:
    response = sign_in(client, kind="extension")

    assert response.status_code == 201
    assert response.json()["token"]
    assert SESSION_COOKIE not in client.cookies


def test_extension_token_is_not_a_browser_session(client: TestClient) -> None:
    token = sign_in(client, kind="extension").json()["token"]

    # Browser-only endpoints take the cookie; an extension token passed as one is refused.
    client.cookies.set(SESSION_COOKIE, token)
    assert client.get(WORKSPACES).status_code == 401


def test_sign_out_with_bearer_ends_the_extension_session(client: TestClient) -> None:
    token = sign_in(client, kind="extension").json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    # Upload accepts the bearer token. Without a file it fails validation (422) once signed in,
    # and authentication (401) once the session is gone.
    upload = f"{WORKSPACES}/{TEAM_WORKSPACE_ID}/meetings"

    assert client.post(upload, headers=headers).status_code == 422
    assert client.delete(SIGN_OUT, headers=headers).status_code == 204
    assert client.post(upload, headers=headers).status_code == 401
