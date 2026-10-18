from datetime import UTC, datetime, timedelta

import pytest

from .enums import RecordingExpiryStatus
from .retention import recording_expiry_status


@pytest.fixture
def deadline() -> datetime:
    return datetime(2026, 11, 1, 12, tzinfo=UTC)


def test_recording_outside_warning_window_is_available(deadline: datetime) -> None:
    # Arrange
    now = deadline - timedelta(days=8)

    # Act
    result = recording_expiry_status(deadline, now)

    # Assert
    assert result == RecordingExpiryStatus.AVAILABLE


def test_recording_at_warning_boundary_is_expiring_soon(deadline: datetime) -> None:
    # Arrange
    now = deadline - timedelta(days=7)

    # Act
    result = recording_expiry_status(deadline, now)

    # Assert
    assert result == RecordingExpiryStatus.EXPIRING_SOON


@pytest.mark.parametrize("elapsed", [timedelta(0), timedelta(microseconds=1)])
def test_recording_at_or_after_deadline_is_expired(deadline: datetime, elapsed: timedelta) -> None:
    # Arrange
    now = deadline + elapsed

    # Act
    result = recording_expiry_status(deadline, now)

    # Assert
    assert result == RecordingExpiryStatus.EXPIRED


AWARE = datetime(2026, 11, 1, 12, tzinfo=UTC)
NAIVE = AWARE.replace(tzinfo=None)


@pytest.mark.parametrize(
    ("deadline", "now"),
    [
        pytest.param(NAIVE, AWARE, id="naive-deadline"),
        pytest.param(AWARE, NAIVE, id="naive-now"),
    ],
)
def test_naive_timestamp_is_rejected(deadline: datetime, now: datetime) -> None:
    # Arrange
    # Act
    # Assert
    with pytest.raises(ValueError, match="timezone-aware"):
        recording_expiry_status(deadline, now)
