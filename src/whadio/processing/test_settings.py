from datetime import timedelta
from typing import Final

import pytest

from conftest import refused_fields

from .settings import JobRecoverySettings

LIMITS: Final = ("unstarted_limit", "transcription_running_limit", "notes_running_limit")


def test_limits_default_to_two_days_unstarted_five_hours_transcribing_one_hour_on_notes() -> None:
    # Act
    settings = JobRecoverySettings()
    # Assert
    assert (
        settings.unstarted_limit,
        settings.transcription_running_limit,
        settings.notes_running_limit,
    ) == (timedelta(days=2), timedelta(hours=5), timedelta(hours=1))


@pytest.mark.parametrize("field", LIMITS)
def test_limit_of_zero_is_refused(field: str) -> None:
    # Act
    found = refused_fields(JobRecoverySettings, {field: "PT0S"})
    # Assert
    assert found == {field}


@pytest.mark.parametrize("field", LIMITS)
def test_limit_of_one_microsecond_is_accepted(field: str) -> None:
    # Act
    found = refused_fields(JobRecoverySettings, {field: "PT0.000001S"})
    # Assert
    assert found == set()
