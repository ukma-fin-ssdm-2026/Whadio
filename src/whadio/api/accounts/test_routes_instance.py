import asyncio
from contextlib import nullcontext
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ...accounts.enums import RegistrationMode
from ...notifications.settings import NotificationSettings, SmtpSettings
from ...shared.errors import Failure, UseCaseError
from ...shared.notes_llm import NotesLlm, OllamaLlm
from .. import composition
from ..app import create_app
from ..composition import CompositionRoot, notes_llm, validate_registration_startup
from ..settings import WebSettings
from .schemas import InstanceRead


def web_settings(mode: RegistrationMode = RegistrationMode.INVITE_ONLY) -> WebSettings:
    return WebSettings.model_validate({"registration_mode": mode, "broker": None})


def notification_settings(*, smtp: bool) -> NotificationSettings:
    relay = SmtpSettings(host="localhost", from_address="noreply@example.com") if smtp else None
    return NotificationSettings.model_validate({"smtp": relay, "public_url": "https://example.com"})


def test_instance_is_public_and_defaults_to_invite_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WHADIO_REGISTRATION_MODE", raising=False)
    app = create_app(web_settings=WebSettings.model_validate({"broker": None}))
    client = TestClient(app)
    # Act
    response = client.get("/api/v1/instance")
    # Assert
    assert (response.status_code, InstanceRead.model_validate_json(response.content)) == (
        200,
        InstanceRead(registration_mode=RegistrationMode.INVITE_ONLY, api_version=app.version),
    )


@pytest.mark.parametrize("mode", list(RegistrationMode))
def test_instance_reports_the_injected_mode(mode: RegistrationMode) -> None:
    # Arrange
    client = TestClient(create_app(web_settings=web_settings(mode)))
    # Act
    response = client.get("/api/v1/instance")
    # Assert
    assert InstanceRead.model_validate_json(response.content).registration_mode is mode


def test_instance_does_not_reload_web_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    client = TestClient(create_app(web_settings=web_settings(RegistrationMode.VERIFIED)))
    monkeypatch.setenv("WHADIO_REGISTRATION_MODE", "invalid")
    monkeypatch.setenv("WHADIO_BROKER__URL", "invalid")
    # Act
    response = client.get("/api/v1/instance")
    # Assert
    assert (
        InstanceRead.model_validate_json(response.content).registration_mode
        is RegistrationMode.VERIFIED
    )


def test_instance_reports_the_application_version() -> None:
    # Arrange
    app = create_app(web_settings=web_settings())
    app.version = "0.2.0"
    client = TestClient(app)
    # Act
    response = client.get("/api/v1/instance")
    # Assert
    assert InstanceRead.model_validate_json(response.content).api_version == app.version


def test_invalid_registration_mode_is_refused() -> None:
    # Act
    with pytest.raises(ValidationError) as failure:
        WebSettings.model_validate({"registration_mode": "open", "broker": None})
    # Assert
    assert failure.value.errors()[0]["loc"] == ("registration_mode",)


@pytest.mark.parametrize("mode", list(RegistrationMode))
@pytest.mark.parametrize("smtp", [False, True])
def test_registration_startup_requires_smtp_only_for_verified_mode(
    mode: RegistrationMode, *, smtp: bool
) -> None:
    # Arrange
    settings, notifications = web_settings(mode), notification_settings(smtp=smtp)
    expectation = (
        pytest.raises(ValueError, match="requires an SMTP relay")
        if mode is RegistrationMode.VERIFIED and not smtp
        else nullcontext()
    )
    # Act
    with expectation:
        validate_registration_startup(settings, notifications)


def test_web_startup_validates_the_cached_registration_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    monkeypatch.chdir(tmp_path)
    root = CompositionRoot(web_settings=web_settings(RegistrationMode.VERIFIED))
    monkeypatch.setenv("WHADIO_REGISTRATION_MODE", "invite-only")
    notifications = notification_settings(smtp=False)
    monkeypatch.setattr(composition, "load_notification_settings", lambda: notifications)

    async def start() -> None:
        async with root.lifespan(FastAPI()):
            pytest.fail("Web startup accepted verified mode without SMTP")

    # Act
    with pytest.raises(ValueError, match="requires an SMTP relay"):
        asyncio.run(start(), loop_factory=asyncio.SelectorEventLoop)


def started_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> CompositionRoot:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WHADIO_NOTES__LLM__PROVIDER", raising=False)
    monkeypatch.delenv("WHADIO_NOTES__LLM__MODEL", raising=False)
    notifications = notification_settings(smtp=False)
    monkeypatch.setattr(composition, "load_notification_settings", lambda: notifications)
    return CompositionRoot(web_settings=web_settings())


def test_web_refuses_to_start_without_the_notes_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    root = started_root(monkeypatch, tmp_path)

    async def start() -> None:
        async with root.lifespan(FastAPI()):
            pytest.fail("Web startup accepted an instance without a notes provider")

    # Act / Assert
    with pytest.raises(ValidationError, match="notes"):
        asyncio.run(start(), loop_factory=asyncio.SelectorEventLoop)


def test_web_startup_loads_the_configured_notes_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    root = started_root(monkeypatch, tmp_path)
    monkeypatch.setenv("WHADIO_NOTES__LLM__PROVIDER", "ollama")
    monkeypatch.setenv("WHADIO_NOTES__LLM__MODEL", "gemma4:12b-it-qat")

    async def start() -> NotesLlm:
        async with root.lifespan(FastAPI()):
            return root.notes_llm()

    # Act
    llm = asyncio.run(start(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert llm == OllamaLlm(provider="ollama", model="gemma4:12b-it-qat")


def test_notes_model_is_unavailable_before_startup() -> None:
    # Arrange
    app = create_app(web_settings=web_settings())
    # Act
    with pytest.raises(UseCaseError) as failure:
        app.dependency_overrides[notes_llm]()
    # Assert
    assert failure.value.code is Failure.INTEGRATION_UNAVAILABLE


def test_specification_builds_without_notes_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WHADIO_NOTES__LLM__PROVIDER", raising=False)
    # Act
    specification = create_app(web_settings=web_settings()).openapi()
    # Assert
    assert "/api/v1/workspaces" in specification["paths"]
