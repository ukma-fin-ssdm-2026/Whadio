from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from .settings import MeetingSettings


def test_refused_settings_do_not_show_the_storage_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    secret_key = uuid4().hex
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WHADIO_STORAGE__ACCESS_KEY", raising=False)
    monkeypatch.setenv("WHADIO_STORAGE__SECRET_KEY", secret_key)

    # Act
    with pytest.raises(ValidationError) as failure:
        MeetingSettings.model_validate({})

    # Assert
    assert secret_key not in str(failure.value)
