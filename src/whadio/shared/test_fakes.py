from datetime import UTC, datetime, timedelta, timezone
from io import BytesIO
from zoneinfo import ZoneInfo

import pytest

from .fakes import FixedClock, InMemoryObjectStorage
from .storage import ObjectStorageError, PresignedUrl

_AT = datetime(2026, 10, 11, 12, tzinfo=UTC)


def test_fixed_clock_moves_only_when_advanced() -> None:
    # Arrange
    clock = FixedClock(_AT)
    # Act
    clock.advance(timedelta(minutes=5))
    # Assert
    assert (clock(), clock()) == (_AT + timedelta(minutes=5), _AT + timedelta(minutes=5))


@pytest.mark.parametrize(
    "at",
    [_AT.replace(tzinfo=None), _AT.replace(tzinfo=timezone(timedelta(hours=3)))],
    ids=["naive", "kyiv-offset"],
)
def test_fixed_clock_refuses_a_time_that_is_not_utc(at: datetime) -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="aware UTC"):
        FixedClock(at)


def test_fixed_clock_advances_in_utc_across_a_daylight_saving_change() -> None:
    # Arrange
    clock = FixedClock(datetime(2026, 3, 29, 0, 30, tzinfo=ZoneInfo("Europe/London")))
    # Act
    clock.advance(timedelta(hours=2))
    # Assert
    assert clock() == datetime(2026, 3, 29, 2, 30, tzinfo=UTC)


def test_deleted_object_is_no_longer_stored() -> None:
    # Arrange
    storage = InMemoryObjectStorage()
    storage.put("a", BytesIO(b"audio"), content_type="audio/wav")
    # Act
    storage.delete("a")
    # Assert
    assert (storage.objects, storage.deleted) == ({}, ["a"])


def test_failing_put_stores_nothing() -> None:
    # Arrange
    storage = InMemoryObjectStorage(fail_put=True)
    # Act
    with pytest.raises(ObjectStorageError):
        storage.put("a", BytesIO(b"audio"), content_type="audio/wav")
    # Assert
    assert (storage.objects, storage.uploaded) == ({}, [])


def test_failing_delete_keeps_the_object() -> None:
    # Arrange
    storage = InMemoryObjectStorage()
    storage.put("a", BytesIO(b"audio"), content_type="audio/wav")
    storage.fail_delete = True
    # Act
    with pytest.raises(ObjectStorageError):
        storage.delete("a")
    # Assert
    assert (storage.objects, storage.deleted) == ({"a": b"audio"}, [])


def test_presigned_link_expires_its_lifetime_after_the_clock() -> None:
    # Arrange
    storage = InMemoryObjectStorage(now=FixedClock(_AT))
    # Act
    link = storage.presign_get("meetings/a.wav", expires_in=timedelta(minutes=5))
    # Assert
    assert link == PresignedUrl(
        "http://storage.test/recordings/meetings/a.wav", _AT + timedelta(minutes=5)
    )


@pytest.mark.parametrize(
    "expires_in",
    [
        pytest.param(timedelta(seconds=1), id="bva-min"),
        pytest.param(timedelta(seconds=2), id="bva-above-min"),
        pytest.param(timedelta(days=7, seconds=-1), id="bva-below-max"),
        pytest.param(timedelta(days=7), id="bva-max"),
    ],
)
def test_presign_accepts_a_lifetime_the_real_storage_accepts(expires_in: timedelta) -> None:
    # Arrange
    storage = InMemoryObjectStorage(now=FixedClock(_AT))
    # Act
    link = storage.presign_get("a", expires_in=expires_in)
    # Assert
    assert link.expires_at == _AT + expires_in


@pytest.mark.parametrize(
    "expires_in",
    [
        pytest.param(timedelta(0), id="bva-below-min"),
        pytest.param(timedelta(milliseconds=999), id="bva-below-min-by-a-fraction"),
        pytest.param(timedelta(days=7, seconds=1), id="bva-above-max"),
        pytest.param(timedelta(seconds=1.5), id="fraction-of-a-second"),
    ],
)
def test_presign_refuses_a_lifetime_the_real_storage_refuses(expires_in: timedelta) -> None:
    # Arrange
    storage = InMemoryObjectStorage()
    # Act / Assert
    with pytest.raises(ValueError, match="presigned URL lives whole seconds"):
        storage.presign_get("a", expires_in=expires_in)
