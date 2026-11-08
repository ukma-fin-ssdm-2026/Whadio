import math
from datetime import timedelta
from pathlib import Path
from typing import Final
from uuid import uuid4

import pytest
from pydantic import ValidationError

from conftest import refused_fields

from .settings import SchedulerSettings

_EPSILON: Final = math.ulp(0.0)


@pytest.mark.parametrize(
    ("interval", "refused"),
    [
        pytest.param(-_EPSILON, {"retention_interval_seconds"}, id="bva-below-bound"),
        pytest.param(0.0, {"retention_interval_seconds"}, id="bva-on-bound"),
        pytest.param(_EPSILON, set[str](), id="bva-above-bound"),
    ],
)
def test_retention_interval_must_be_above_zero(interval: float, refused: set[str]) -> None:
    # Act
    found = refused_fields(
        SchedulerSettings,
        {
            "storage": {
                "endpoint_url": "http://seaweedfs:8333",
                "access_key": "whadio-test",
                "secret_key": uuid4().hex,
            },
            "retention_interval_seconds": interval,
        },
    )

    # Assert
    assert found == refused


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
        SchedulerSettings.model_validate({})

    # Assert
    assert secret_key not in str(failure.value)


def test_job_recovery_limit_is_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WHADIO_STORAGE__ENDPOINT_URL", "http://seaweedfs:8333")
    monkeypatch.setenv("WHADIO_STORAGE__ACCESS_KEY", "whadio-test")
    monkeypatch.setenv("WHADIO_STORAGE__SECRET_KEY", uuid4().hex)
    monkeypatch.setenv("WHADIO_JOB_RECOVERY__UNSTARTED_LIMIT", "PT1M")

    # Act
    settings = SchedulerSettings.model_validate({})

    # Assert
    assert settings.job_recovery.unstarted_limit == timedelta(minutes=1)
