from ...contracts.common import Segment
from .diarization import SpeakerTurn
from .recognition import RecognizedSegment, Word
from .speakers import SpeakerIndex, attribute_speakers

_TURNS = (
    SpeakerTurn(start=0.0, end=4.0, speaker="SPEAKER_01"),
    SpeakerTurn(start=4.0, end=8.0, speaker="SPEAKER_00"),
    SpeakerTurn(start=10.0, end=12.0, speaker="SPEAKER_01"),
)


def _segment(*words: Word) -> RecognizedSegment:
    return RecognizedSegment(
        start=words[0].start,
        end=words[-1].end,
        text="".join(word.text for word in words),
        words=words,
    )


def test_word_goes_to_the_speaker_who_talks_longest_during_it() -> None:
    # Arrange
    index = SpeakerIndex(_TURNS)

    # Act
    speaker = index.speaker_of(3.5, 5.0)

    # Assert
    assert speaker == "SPEAKER_00"


def test_word_in_a_pause_goes_to_the_speaker_of_the_nearest_turn() -> None:
    # Arrange
    index = SpeakerIndex(_TURNS)

    # Act
    speaker = index.speaker_of(9.2, 9.6)

    # Assert
    assert speaker == "SPEAKER_01"


def test_word_before_every_turn_goes_to_the_first_speaker() -> None:
    # Arrange
    index = SpeakerIndex(sorted(_TURNS, key=lambda turn: -turn.start))

    # Act
    speaker = index.speaker_of(-1.0, -0.5)

    # Assert
    assert speaker == "SPEAKER_01"


def test_speaker_is_unknown_without_turns() -> None:
    # Arrange
    index = SpeakerIndex(())

    # Act
    speaker = index.speaker_of(1.0, 2.0)

    # Assert
    assert speaker is None


def test_segment_is_split_where_the_speaker_changes() -> None:
    # Arrange
    recognized = _segment(
        Word(start=2.0, end=3.0, text=" So"),
        Word(start=3.0, end=3.8, text=" done."),
        Word(start=4.2, end=5.0, text=" Next"),
        Word(start=5.0, end=6.0, text=" item."),
    )

    # Act
    attribution = attribute_speakers(_TURNS, [recognized])

    # Assert
    assert attribution.segments == (
        Segment(start_seconds=2.0, end_seconds=3.8, speaker="Speaker 1", text="So done."),
        Segment(start_seconds=4.2, end_seconds=6.0, speaker="Speaker 2", text="Next item."),
    )


def test_speakers_are_labelled_in_order_of_their_first_words() -> None:
    # Arrange
    recognized = [
        _segment(Word(start=5.0, end=6.0, text=" First")),
        _segment(Word(start=1.0, end=2.0, text=" Second")),
    ]

    # Act
    attribution = attribute_speakers(_TURNS, recognized)

    # Assert
    assert [segment.speaker for segment in attribution.segments] == ["Speaker 1", "Speaker 2"]


def test_speakers_list_only_those_who_said_something() -> None:
    # Arrange
    recognized = [_segment(Word(start=4.5, end=5.5, text=" Alone"))]

    # Act
    attribution = attribute_speakers(_TURNS, recognized)

    # Assert
    assert attribution.speakers == ("Speaker 1",)


def test_segment_without_words_takes_the_speaker_of_its_interval() -> None:
    # Arrange
    recognized = RecognizedSegment(start=10.5, end=11.5, text=" Whole segment.", words=())

    # Act
    attribution = attribute_speakers(_TURNS, [recognized])

    # Assert
    assert attribution.segments == (
        Segment(start_seconds=10.5, end_seconds=11.5, speaker="Speaker 1", text="Whole segment."),
    )


def test_segments_have_no_speaker_when_diarization_found_none() -> None:
    # Arrange
    recognized = [_segment(Word(start=1.0, end=2.0, text=" Hello"))]

    # Act
    attribution = attribute_speakers((), recognized)

    # Assert
    assert (attribution.speakers, attribution.segments[0].speaker) == ((), None)


def test_blank_segments_are_left_out() -> None:
    # Arrange
    recognized = [RecognizedSegment(start=1.0, end=2.0, text="  ", words=())]

    # Act
    attribution = attribute_speakers(_TURNS, recognized)

    # Assert
    assert attribution.segments == ()


def test_zero_length_word_still_ends_after_it_starts() -> None:
    # Arrange
    recognized = [_segment(Word(start=1.0, end=1.0, text=" Oh"))]

    # Act
    attribution = attribute_speakers(_TURNS, recognized)

    # Assert
    [segment] = attribution.segments
    assert segment.end_seconds > segment.start_seconds
