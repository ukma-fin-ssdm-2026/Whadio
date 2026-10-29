import asyncio
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ...accounts.enums import RegistrationMode
from ..app import create_app
from ..composition import CompositionRoot
from ..settings import WebSettings
from .schemas import InstanceRead


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for key in tuple(os.environ):
        if key == "WHADIO_REGISTRATION_MODE" or key.startswith("WHADIO_SMTP"):
            monkeypatch.delenv(key)


async def start_web() -> None:
    async with CompositionRoot().lifespan(FastAPI()):
        pass


def test_instance_is_public_and_defaults_to_invite_only() -> None:
    # Arrange
    app = create_app()
    client = TestClient(app)
    # Act
    response = client.get("/api/v1/instance")
    # Assert
    assert (response.status_code, InstanceRead.model_validate_json(response.content)) == (
        200,
        InstanceRead(registration_mode=RegistrationMode.INVITE_ONLY, api_version=app.version),
    )


def test_instance_reports_the_configured_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_REGISTRATION_MODE", "verified")
    client = TestClient(create_app())
    # Act
    response = client.get("/api/v1/instance")
    # Assert
    assert InstanceRead.model_validate_json(response.content).registration_mode == "verified"


def test_instance_reports_the_application_version() -> None:
    # Arrange
    app = create_app()
    app.version = "0.2.0"
    client = TestClient(app)
    # Act
    response = client.get("/api/v1/instance")
    # Assert
    assert InstanceRead.model_validate_json(response.content).api_version == app.version


def test_invalid_registration_mode_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_REGISTRATION_MODE", "open")
    # Act
    with pytest.raises(ValidationError) as failure:
        WebSettings.model_validate({})
    # Assert
    assert failure.value.errors()[0]["loc"] == ("registration_mode",)


def test_verified_web_requires_an_smtp_relay(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_REGISTRATION_MODE", "verified")
    # Act
    with pytest.raises(ValueError, match="requires an SMTP relay"):
        asyncio.run(start_web(), loop_factory=asyncio.SelectorEventLoop)


def test_verified_web_accepts_a_configured_smtp_relay(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_REGISTRATION_MODE", "verified")
    monkeypatch.setenv("WHADIO_PUBLIC_URL", "https://example.com")
    monkeypatch.setenv("WHADIO_SMTP__HOST", "localhost")
    monkeypatch.setenv("WHADIO_SMTP__FROM_ADDRESS", "noreply@example.com")
    # Act
    result = asyncio.run(start_web(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert result is None


def test_invite_only_web_needs_no_smtp_relay() -> None:
    # Arrange
    settings = WebSettings.model_validate({})
    # Act
    asyncio.run(start_web(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert settings.registration_mode is RegistrationMode.INVITE_ONLY
