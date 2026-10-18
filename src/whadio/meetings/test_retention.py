from datetime import UTC, datetime, timedelta

import pytest

from .enums import RecordingExpiryStatus
from .retention import recording_expiry_status


def test_recording_outside_warning_window_is_available() -> None:
    # Arrange
    deadline = datetime(2026, 11, 1, 12, tzinfo=UTC)
    now = deadline - timedelta(days=8)

    # Act
    result = recording_expiry_status(deadline, now)

    # Assert
    assert result == RecordingExpiryStatus.AVAILABLE


def test_recording_at_warning_boundary_is_expiring_soon() -> None:
    # Arrange
    deadline = datetime(2026, 11, 1, 12, tzinfo=UTC)
    now = deadline - timedelta(days=7)

    # Act
    result = recording_expiry_status(deadline, now)

    # Assert
    assert result == RecordingExpiryStatus.EXPIRING_SOON


@pytest.mark.parametrize("elapsed", [timedelta(0), timedelta(microseconds=1)])
def test_recording_at_or_after_deadline_is_expired(elapsed: timedelta) -> None:
    # Arrange
    deadline = datetime(2026, 11, 1, 12, tzinfo=UTC)
    now = deadline + elapsed

    # Act
    result = recording_expiry_status(deadline, now)

    # Assert
    assert result == "expired"
