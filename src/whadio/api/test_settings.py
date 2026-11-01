from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from .settings import WebSettings


def test_refused_settings_do_not_show_a_mistyped_broker_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    password = uuid4().hex[:8]
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WHADIO_BROKER__URL", raising=False)
    monkeypatch.setenv("WHADIO_BROKER__URI", f"amqp://web:{password}@localhost/whadio")

    # Act
    with pytest.raises(ValidationError) as failure:
        WebSettings.model_validate({})

    # Assert
    assert password not in str(failure.value)
