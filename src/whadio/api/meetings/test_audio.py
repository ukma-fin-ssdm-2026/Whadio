from io import BytesIO
from pathlib import Path

from .audio import is_supported_audio

TESTDATA = Path(__file__).parent / "testdata"


def test_mp4_with_an_audio_track_is_accepted() -> None:
    # Arrange
    recording = BytesIO((TESTDATA / "tone-with-video.mp4").read_bytes())
    # Act
    supported = is_supported_audio(recording)
    # Assert
    assert supported


def test_mp4_without_an_audio_track_is_refused() -> None:
    # Arrange
    recording = BytesIO((TESTDATA / "video-only.mp4").read_bytes())
    # Act
    supported = is_supported_audio(recording)
    # Assert
    assert not supported


def test_bytes_that_are_not_audio_are_refused() -> None:
    # Arrange
    recording = BytesIO(b"not audio at all")
    # Act
    supported = is_supported_audio(recording)
    # Assert
    assert not supported
