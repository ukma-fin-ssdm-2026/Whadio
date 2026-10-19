from ..contracts.common import Segment
from .speakers import SpeakerEvent, resolve_speaker_names


def segment(start: float, end: float, speaker: str | None = "Speaker 1") -> Segment:
    return Segment(start_seconds=start, end_seconds=end, speaker=speaker, text="Привіт")


def test_label_heard_while_one_participant_spoke_gets_their_name() -> None:
    # Arrange
    events = (SpeakerEvent(0.0, ("Alice",)),)

    # Act
    names = resolve_speaker_names(events, (segment(1.0, 3.0),), 10.0)

    # Assert
    assert names == {"Speaker 1": "Alice"}


def test_recording_without_events_names_nobody() -> None:
    # Arrange
    segments = (segment(1.0, 3.0),)

    # Act
    names = resolve_speaker_names((), segments, 10.0)

    # Assert
    assert names == {}


def test_participants_speaking_at_once_name_nobody() -> None:
    # Arrange
    events = (SpeakerEvent(0.0, ("Alice", "Bob")),)

    # Act
    names = resolve_speaker_names(events, (segment(1.0, 3.0),), 10.0)

    # Assert
    assert names == {}


def test_label_split_evenly_between_two_participants_keeps_its_number() -> None:
    # Arrange
    events = (SpeakerEvent(0.0, ("Alice",)), SpeakerEvent(2.0, ("Bob",)))

    # Act
    names = resolve_speaker_names(events, (segment(1.0, 3.0),), 10.0)

    # Assert
    assert names == {}


def test_two_labels_matching_the_same_participant_keep_their_numbers() -> None:
    # Arrange
    events = (SpeakerEvent(0.0, ("Alice",)),)
    segments = (segment(1.0, 3.0), segment(4.0, 6.0, "Speaker 2"))

    # Act
    names = resolve_speaker_names(events, segments, 10.0)

    # Assert
    assert names == {}


def test_event_lasts_until_the_next_one_across_chunks() -> None:
    # Arrange
    events = (SpeakerEvent(0.5, ("Alice",)), SpeakerEvent(8.0, ("Bob",)))

    # Act
    names = resolve_speaker_names(events, (segment(3.0, 5.0),), 10.0)

    # Assert
    assert names == {"Speaker 1": "Alice"}


def test_events_out_of_order_are_read_in_recording_time() -> None:
    # Arrange
    events = (SpeakerEvent(4.0, ("Bob",)), SpeakerEvent(0.0, ("Alice",)))
    segments = (segment(1.0, 3.0), segment(5.0, 7.0, "Speaker 2"))

    # Act
    names = resolve_speaker_names(events, segments, 10.0)

    # Assert
    assert names == {"Speaker 1": "Alice", "Speaker 2": "Bob"}


def test_last_event_lasts_until_the_end_of_the_recording() -> None:
    # Arrange
    events = (SpeakerEvent(0.0, ()), SpeakerEvent(5.0, ("Alice",)))

    # Act
    names = resolve_speaker_names(events, (segment(7.0, 9.0),), 10.0)

    # Assert
    assert names == {"Speaker 1": "Alice"}


def test_segment_without_a_speaker_names_nobody() -> None:
    # Arrange
    events = (SpeakerEvent(0.0, ("Alice",)),)

    # Act
    names = resolve_speaker_names(events, (segment(1.0, 3.0, None),), 10.0)

    # Assert
    assert names == {}
