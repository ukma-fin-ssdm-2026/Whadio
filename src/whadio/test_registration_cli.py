from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, delete
from typer.testing import CliRunner

from .accounts.models import PendingRegistration
from .cli import app
from .shared.database import DatabaseSettings


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WHADIO_PUBLIC_URL", "https://example.com/whadio/")


def test_registration_command_refuses_invalid_email() -> None:
    # Arrange
    runner = CliRunner()
    # Act
    result = runner.invoke(app, ["links", "registration", "--email", "invalid"])
    # Assert
    assert (result.exit_code != 0, "must be an email address" in result.output) == (True, True)


def test_registration_command_requires_a_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.delenv("WHADIO_PUBLIC_URL")
    # Act
    result = CliRunner().invoke(app, ["links", "registration", "--email", "alice@example.com"])
    # Assert
    assert (result.exit_code, "WHADIO_PUBLIC_URL" in result.output) == (1, True)


@pytest.mark.slow
def test_registration_command_prints_a_redeemable_link(
    database_settings: DatabaseSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_DB_HOST", database_settings.host)
    monkeypatch.setenv("WHADIO_DB_PORT", str(database_settings.port))
    monkeypatch.setenv("WHADIO_DB_NAME", database_settings.name)
    monkeypatch.setenv("WHADIO_DB_APP_PASSWORD", database_settings.app_password.get_secret_value())
    email = f"{uuid4()}@example.com"
    engine = create_engine(database_settings.application_url(), hide_parameters=True)
    try:
        # Act
        result = CliRunner().invoke(app, ["links", "registration", "--email", email])
        link = urlsplit(result.stdout.strip())
        with engine.connect() as connection:
            stored = (
                connection.execute(
                    PendingRegistration.__table__.select().where(PendingRegistration.email == email)
                )
                .mappings()
                .one()
            )
        # Assert
        assert (
            result.exit_code,
            link.scheme,
            link.netloc,
            link.path,
            bool(parse_qs(link.fragment).get("token")),
            stored["pending_registration_id"],
        ) == (
            0,
            "https",
            "example.com",
            f"/whadio/registrations/{stored['pending_registration_id']}",
            True,
            UUID(link.path.rsplit("/", 1)[1]),
        )
    finally:
        with engine.begin() as connection:
            connection.execute(
                delete(PendingRegistration).where(PendingRegistration.email == email)
            )
        engine.dispose()
