from datetime import timedelta

import pytest

from conftest import refused_fields

from .settings import JobRecoverySettings


def test_unstarted_limit_defaults_to_two_days() -> None:
    # Act
    settings = JobRecoverySettings()
    # Assert
    assert settings.unstarted_limit == timedelta(days=2)


@pytest.mark.parametrize(
    ("limit", "refused"),
    [
        pytest.param("PT0S", {"unstarted_limit"}, id="bva-on-bound"),
        pytest.param("PT0.000001S", set[str](), id="bva-above-bound"),
    ],
)
def test_unstarted_limit_must_be_above_zero(limit: str, refused: set[str]) -> None:
    # Act
    found = refused_fields(JobRecoverySettings, {"unstarted_limit": limit})
    # Assert
    assert found == refused
