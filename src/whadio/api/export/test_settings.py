from pathlib import Path

import pytest
from pydantic import ValidationError

from ..app import create_app
from ..composition import CompositionRoot


def test_invalid_export_public_url_is_refused_when_the_app_is_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_PUBLIC_URL", "https://user:password@example.com")
    # Act
    with pytest.raises(ValidationError) as failure:
        create_app()
    # Assert
    assert failure.value.error_count() == 1


def test_export_public_url_is_resolved_once_per_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_PUBLIC_URL", "https://canonical.example/whadio/")
    root = CompositionRoot()
    # Act
    monkeypatch.setenv("WHADIO_PUBLIC_URL", "https://other.example")
    # Assert
    assert root.public_url == "https://canonical.example/whadio/"


def test_export_retains_its_local_development_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WHADIO_PUBLIC_URL", raising=False)
    monkeypatch.delenv("WHADIO_API_PUBLIC_URL", raising=False)
    # Act
    root = CompositionRoot()
    # Assert
    assert (root.public_url, root.api_public_url) == (
        "http://localhost:3000",
        "http://localhost:3000",
    )


def test_api_public_url_defaults_to_the_web_base(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_PUBLIC_URL", "https://app.example/whadio/")
    monkeypatch.delenv("WHADIO_API_PUBLIC_URL", raising=False)
    # Act
    root = CompositionRoot()
    # Assert
    assert root.api_public_url == root.public_url == "https://app.example/whadio/"


def test_api_public_url_is_resolved_once_per_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_API_PUBLIC_URL", "https://api.example/service/")
    root = CompositionRoot()
    # Act
    monkeypatch.setenv("WHADIO_API_PUBLIC_URL", "https://other.example/")
    # Assert
    assert root.api_public_url == "https://api.example/service/"


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@api.example/",
        "https://api.example/?query=yes",
        "https://api.example/#fragment",
        "ftp://api.example/",
    ],
)
def test_invalid_api_public_url_is_refused_when_the_app_is_built(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_API_PUBLIC_URL", url)
    # Act
    with pytest.raises(ValidationError) as failure:
        create_app()
    # Assert
    assert failure.value.error_count() == 1
