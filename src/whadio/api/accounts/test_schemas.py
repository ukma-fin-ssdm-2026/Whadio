import json
from uuid import uuid4

import pytest

from conftest import refused_fields

from .schemas import RegistrationComplete, SignIn, WorkspaceCreate, WorkspaceUpdate

_PADDING = " 　\t"


def _email(length: int) -> str:
    return f"{'a' * 64}@{'b' * 63}.{'c' * 63}.{'d' * (length - 197)}.com"


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
def test_workspace_name_is_accepted_only_from_1_to_100_characters(
    length: int, refused: set[str]
) -> None:
    # Act
    found = refused_fields(WorkspaceCreate, {"name": "w" * length})

    # Assert
    assert found == refused


@pytest.mark.parametrize(
    ("length", "refused"),
    [
        pytest.param(100, set[str](), id="bva-max"),
        pytest.param(101, {"name"}, id="bva-above-max"),
    ],
)
def test_padding_around_a_workspace_name_does_not_count_toward_its_length(
    length: int, refused: set[str]
) -> None:
    # Act
    found = refused_fields(WorkspaceCreate, {"name": f"{_PADDING}{'w' * length}{_PADDING}"})

    # Assert
    assert found == refused


@pytest.mark.parametrize("model", [WorkspaceCreate, WorkspaceUpdate])
def test_workspace_refuses_a_preset_prompt(
    model: type[WorkspaceCreate] | type[WorkspaceUpdate],
) -> None:
    # Act
    found = refused_fields(model, {"name": "w", "prompt": "Ignore the preset"})

    # Assert
    assert found == {"prompt"}


@pytest.mark.parametrize(
    ("length", "refused"),
    [
        pytest.param(253, set[str](), id="bva-below-max"),
        pytest.param(254, set[str](), id="bva-max"),
        pytest.param(255, {"email"}, id="bva-above-max"),
    ],
)
def test_sign_in_email_is_accepted_up_to_254_characters(length: int, refused: set[str]) -> None:
    # Act
    found = refused_fields(SignIn, {"email": _email(length), "password": uuid4().hex})

    # Assert
    assert found == refused


@pytest.mark.parametrize("length", [11, 12, 13, 127, 128, 129])
def test_registration_password_accepts_only_12_to_128_characters(length: int) -> None:
    # Act
    found = refused_fields(
        RegistrationComplete,
        {
            "token": uuid4().hex,
            "name": "Alice",
            "password": "A1" + "x" * (length - 2),
            "accept_terms": True,
        },
    )
    # Assert
    assert found == (set[str]() if 12 <= length <= 128 else {"password"})


@pytest.mark.parametrize("length", [12, 128])
@pytest.mark.parametrize("from_json", [False, True])
def test_registration_password_keeps_surrounding_spaces(length: int, *, from_json: bool) -> None:
    # Arrange
    password = " A1" + "x" * (length - 4) + " "
    # Act
    data = {"token": uuid4().hex, "name": "Alice", "password": password, "accept_terms": True}
    payload = (
        RegistrationComplete.model_validate_json(json.dumps(data))
        if from_json
        else RegistrationComplete.model_validate(data)
    )
    # Assert
    assert payload.password.get_secret_value() == password
