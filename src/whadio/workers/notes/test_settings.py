from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from .settings import load_notes_worker_settings


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WHADIO_BROKER__URL", "amqp://notes:secret@localhost:5672/whadio")
    monkeypatch.setenv("WHADIO_NOTES__API_KEY", "sk-ant-test")


def test_settings_read_nested_variables_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_NOTES__JOB_TIMEOUT", "PT20M")

    # Act
    settings = load_notes_worker_settings()

    # Assert
    assert settings.notes.job_timeout == timedelta(minutes=20)


def test_settings_read_the_dotenv_file_of_the_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    monkeypatch.delenv("WHADIO_NOTES__API_KEY")
    (tmp_path / ".env").write_text("WHADIO_NOTES__API_KEY=sk-ant-from-file\n", encoding="utf-8")

    # Act
    settings = load_notes_worker_settings()

    # Assert
    assert settings.notes.api_key.get_secret_value() == "sk-ant-from-file"


def test_broker_user_comes_from_the_broker_url() -> None:
    # Act
    settings = load_notes_worker_settings()

    # Assert
    assert settings.broker.user == "notes"


def test_settings_without_an_api_key_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_NOTES__API_KEY", "")

    # Act / Assert
    with pytest.raises(ValidationError, match="api_key"):
        load_notes_worker_settings()
