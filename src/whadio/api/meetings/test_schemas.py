import pytest

from conftest import refused_fields

from .schemas import MeetingUpdate

_PADDING = " 　\t"


@pytest.mark.parametrize(
    ("length", "refused"),
    [
        pytest.param(0, {"name"}, id="bva-below-min"),
        pytest.param(1, set[str](), id="bva-min"),
        pytest.param(2, set[str](), id="bva-above-min"),
        pytest.param(100, set[str](), id="bva-nominal"),
        pytest.param(199, set[str](), id="bva-below-max"),
        pytest.param(200, set[str](), id="bva-max"),
        pytest.param(201, {"name"}, id="bva-above-max"),
    ],
)
def test_meeting_name_is_accepted_only_from_1_to_200_characters(
    length: int, refused: set[str]
) -> None:
    # Act
    found = refused_fields(MeetingUpdate, {"name": "m" * length})

    # Assert
    assert found == refused


@pytest.mark.parametrize(
    ("length", "refused"),
    [
        pytest.param(200, set[str](), id="bva-max"),
        pytest.param(201, {"name"}, id="bva-above-max"),
    ],
)
def test_padding_around_a_meeting_name_does_not_count_toward_its_length(
    length: int, refused: set[str]
) -> None:
    # Act
    found = refused_fields(MeetingUpdate, {"name": f"{_PADDING}{'m' * length}{_PADDING}"})

    # Assert
    assert found == refused
