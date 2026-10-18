from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from .enums import RecordingExpiryStatus
from .retention import WARNING_PERIOD, recording_expiry_status

AWARE = datetime(2026, 11, 1, 12, tzinfo=UTC)
NAIVE = AWARE.replace(tzinfo=None)


@pytest.mark.parametrize(
    ("remaining", "expected"),
    [
        pytest.param(
            WARNING_PERIOD + timedelta(microseconds=1),
            RecordingExpiryStatus.AVAILABLE,
            id="before-warning",
        ),
        pytest.param(WARNING_PERIOD, RecordingExpiryStatus.EXPIRING_SOON, id="at-warning"),
        pytest.param(
            WARNING_PERIOD - timedelta(microseconds=1),
            RecordingExpiryStatus.EXPIRING_SOON,
            id="after-warning",
        ),
        pytest.param(
            timedelta(microseconds=1), RecordingExpiryStatus.EXPIRING_SOON, id="before-deadline"
        ),
        pytest.param(timedelta(0), RecordingExpiryStatus.EXPIRED, id="at-deadline"),
        pytest.param(
            timedelta(microseconds=-1), RecordingExpiryStatus.EXPIRED, id="after-deadline"
        ),
    ],
)
def test_recording_expiry_boundaries(remaining: timedelta, expected: RecordingExpiryStatus) -> None:
    # Arrange
    now = AWARE - remaining

    # Act
    result = recording_expiry_status(AWARE, now)

    # Assert
    assert result == expected


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
    with pytest.raises(ValueError, match=r"^Retention requires an aware timestamp$"):
        recording_expiry_status(deadline, now)


@pytest.mark.parametrize(
    ("deadline", "now", "expected"),
    [
        pytest.param(
            datetime(2026, 11, 1, 0, 30, tzinfo=ZoneInfo("Europe/Kyiv")),
            datetime(2026, 10, 25, 0, 30, tzinfo=ZoneInfo("Europe/Kyiv")),
            RecordingExpiryStatus.AVAILABLE,
            id="autumn-extra-hour",
        ),
        pytest.param(
            datetime(2026, 3, 29, 12, 30, tzinfo=ZoneInfo("Europe/Kyiv")),
            datetime(2026, 3, 22, 12, tzinfo=ZoneInfo("Europe/Kyiv")),
            RecordingExpiryStatus.EXPIRING_SOON,
            id="spring-missing-hour",
        ),
    ],
)
def test_warning_window_uses_elapsed_time_across_daylight_saving(
    deadline: datetime, now: datetime, expected: RecordingExpiryStatus
) -> None:
    # Arrange
    # Act
    result = recording_expiry_status(deadline, now)

    # Assert
    assert result == expected
