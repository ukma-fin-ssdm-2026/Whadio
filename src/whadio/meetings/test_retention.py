from datetime import UTC, datetime, timedelta

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
