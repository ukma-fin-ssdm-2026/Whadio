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
    # Act
    root = CompositionRoot()
    # Assert
    assert root.public_url == "http://localhost:3000"
