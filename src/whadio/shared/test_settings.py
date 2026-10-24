from pathlib import Path

import pytest

from .settings import PublicUrlSettings


def test_public_url_is_optional_without_a_mail_relay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WHADIO_PUBLIC_URL", raising=False)
    # Act
    settings = PublicUrlSettings.model_validate({})
    # Assert
    assert settings.public_url is None


def test_public_url_preserves_a_deployment_path(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_PUBLIC_URL", "https://whadio.example/whadio/")
    # Act
    settings = PublicUrlSettings.model_validate({})
    # Assert
    assert str(settings.public_url) == "https://whadio.example/whadio/"
