from typing import Final

import pytest
from pydantic import BaseModel, JsonValue

from conftest import refused_fields

from .routes_content import FolderInput, TermInput, TermPatch

_PADDING: Final = " 　\t"
_TERM_BASE: Final[dict[type[BaseModel], dict[str, JsonValue]]] = {
    TermInput: {"term": "ASR", "preferred_form": "ASR"},
    TermPatch: {},
}
_TERM_MODELS: Final = pytest.mark.parametrize(
    "model",
    [pytest.param(TermInput, id="create"), pytest.param(TermPatch, id="update")],
)


@pytest.mark.parametrize(
    ("length", "refused"),
    [
        pytest.param(0, {"name"}, id="bva-below-min"),
        pytest.param(1, set[str](), id="bva-min"),
        pytest.param(2, set[str](), id="bva-above-min"),
        pytest.param(50, set[str](), id="bva-nominal"),
        pytest.param(99, set[str](), id="bva-below-max"),
        pytest.param(100, set[str](), id="bva-max"),
        pytest.param(101, {"name"}, id="bva-above-max"),
    ],
)
def test_folder_name_is_accepted_only_from_1_to_100_characters(
    length: int, refused: set[str]
) -> None:
    # Act
    found = refused_fields(FolderInput, {"name": "f" * length})

    # Assert
    assert found == refused


@pytest.mark.parametrize(
    ("length", "refused"),
    [
        pytest.param(100, set[str](), id="bva-max"),
        pytest.param(101, {"name"}, id="bva-above-max"),
    ],
)
def test_padding_around_a_folder_name_does_not_count_toward_its_length(
    length: int, refused: set[str]
) -> None:
    # Act
    found = refused_fields(FolderInput, {"name": f"{_PADDING}{'f' * length}{_PADDING}"})

    # Assert
    assert found == refused


@_TERM_MODELS
@pytest.mark.parametrize("field", ["term", "preferred_form"])
@pytest.mark.parametrize(
    ("length", "accepted"),
    [
        pytest.param(0, False, id="bva-below-min"),
        pytest.param(1, True, id="bva-min"),
        pytest.param(2, True, id="bva-above-min"),
        pytest.param(100, True, id="bva-nominal"),
        pytest.param(199, True, id="bva-below-max"),
        pytest.param(200, True, id="bva-max"),
        pytest.param(201, False, id="bva-above-max"),
    ],
)
def test_glossary_spelling_is_accepted_only_from_1_to_200_characters(
    model: type[BaseModel], field: str, length: int, *, accepted: bool
) -> None:
    # Arrange
    data = {**_TERM_BASE[model], field: "g" * length}

    # Act
    found = refused_fields(model, data)

    # Assert
    assert found == (set[str]() if accepted else {field})


@_TERM_MODELS
@pytest.mark.parametrize("field", ["term", "preferred_form"])
@pytest.mark.parametrize(
    ("length", "accepted"),
    [
        pytest.param(200, True, id="bva-max"),
        pytest.param(201, False, id="bva-above-max"),
    ],
)
def test_padding_around_a_glossary_spelling_does_not_count_toward_its_length(
    model: type[BaseModel], field: str, length: int, *, accepted: bool
) -> None:
    # Arrange
    data = {**_TERM_BASE[model], field: f"{_PADDING}{'g' * length}{_PADDING}"}

    # Act
    found = refused_fields(model, data)

    # Assert
    assert found == (set[str]() if accepted else {field})


@_TERM_MODELS
@pytest.mark.parametrize(
    ("length", "refused"),
    [
        pytest.param(1999, set[str](), id="bva-below-max"),
        pytest.param(2000, set[str](), id="bva-max"),
        pytest.param(2001, {"description"}, id="bva-above-max"),
    ],
)
def test_glossary_description_is_accepted_up_to_2000_characters(
    model: type[BaseModel], length: int, refused: set[str]
) -> None:
    # Arrange
    data = {**_TERM_BASE[model], "description": "d" * length}

    # Act
    found = refused_fields(model, data)

    # Assert
    assert found == refused
