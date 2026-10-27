import math
from datetime import timedelta
from pathlib import Path
from typing import Final

import pytest
from pydantic import SecretStr, ValidationError

from conftest import refused_fields

from .settings import (
    AnthropicSettings,
    NotesSettings,
    OllamaSettings,
    load_notes_worker_settings,
)

_MICROSECOND: Final = 1e-6


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WHADIO_BROKER__URL", "amqp://notes:secret@localhost:5672/whadio")


@pytest.fixture
def anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WHADIO_NOTES__LLM__PROVIDER", "anthropic")
    monkeypatch.setenv("WHADIO_NOTES__LLM__API_KEY", "sk-ant-test")


@pytest.fixture
def ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WHADIO_NOTES__LLM__PROVIDER", "ollama")
    monkeypatch.setenv("WHADIO_NOTES__LLM__MODEL", "gemma3:12b")


def test_settings_read_nested_variables_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_NOTES__JOB_TIMEOUT", "PT20M")

    # Act
    settings = load_notes_worker_settings()

    # Assert
    assert settings.notes.job_timeout == timedelta(minutes=20)


def test_settings_read_the_dotenv_file_of_the_working_directory(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / ".env").write_text(
        "WHADIO_NOTES__LLM__PROVIDER=anthropic\nWHADIO_NOTES__LLM__API_KEY=sk-ant-from-file\n",
        encoding="utf-8",
    )

    # Act
    settings = load_notes_worker_settings()

    # Assert
    assert settings.notes.llm == AnthropicSettings(api_key=SecretStr("sk-ant-from-file"))


def test_broker_user_comes_from_the_broker_url() -> None:
    # Act
    settings = load_notes_worker_settings()

    # Assert
    assert settings.broker.user == "notes"


def test_ollama_is_the_provider_when_none_is_named() -> None:
    # Act
    settings = load_notes_worker_settings()

    # Assert
    assert isinstance(settings.notes.llm, OllamaSettings)


def test_ollama_model_defaults_to_gemma4_12b_qat() -> None:
    # Act
    settings = load_notes_worker_settings()

    # Assert
    assert settings.notes.llm == OllamaSettings(model="gemma4:12b-it-qat")


def test_an_api_key_without_a_provider_keeps_the_built_in_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_NOTES__LLM__API_KEY", "sk-ant-test")

    # Act
    settings = load_notes_worker_settings()

    # Assert
    assert isinstance(settings.notes.llm, OllamaSettings)


@pytest.mark.usefixtures("ollama")
def test_ollama_provider_reads_the_ollama_settings() -> None:
    # Act
    settings = load_notes_worker_settings()

    # Assert
    assert settings.notes.llm == OllamaSettings(provider="ollama", model="gemma3:12b")


def test_settings_with_an_unknown_provider_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_NOTES__LLM__PROVIDER", "olama")

    # Act / Assert
    with pytest.raises(ValidationError, match="union_tag_invalid"):
        load_notes_worker_settings()


@pytest.mark.usefixtures("anthropic")
def test_settings_with_an_empty_api_key_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_NOTES__LLM__API_KEY", "")

    # Act / Assert
    with pytest.raises(ValidationError, match="api_key"):
        load_notes_worker_settings()


def test_anthropic_settings_without_an_api_key_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_NOTES__LLM__PROVIDER", "anthropic")

    # Act / Assert
    with pytest.raises(ValidationError, match="api_key"):
        load_notes_worker_settings()


@pytest.mark.usefixtures("ollama")
def test_ollama_settings_with_an_empty_model_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_NOTES__LLM__MODEL", "")

    # Act / Assert
    with pytest.raises(ValidationError, match="model"):
        load_notes_worker_settings()


@pytest.mark.usefixtures("ollama")
def test_ollama_window_without_room_for_a_prompt_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_NOTES__LLM__NUM_CTX", "16384")
    monkeypatch.setenv("WHADIO_NOTES__MAX_OUTPUT_TOKENS", "15385")

    # Act / Assert
    with pytest.raises(ValidationError, match="num_ctx"):
        load_notes_worker_settings()


@pytest.mark.usefixtures("ollama")
def test_ollama_window_with_the_least_room_for_a_prompt_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_NOTES__LLM__NUM_CTX", "16384")
    monkeypatch.setenv("WHADIO_NOTES__MAX_OUTPUT_TOKENS", "15384")

    # Act
    settings = load_notes_worker_settings()

    # Assert
    assert settings.notes.max_prompt_tokens == 1_000


@pytest.mark.usefixtures("anthropic")
def test_anthropic_prompt_budget_is_the_input_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_NOTES__MAX_INPUT_TOKENS", "120000")

    # Act
    settings = load_notes_worker_settings()

    # Assert
    assert settings.notes.max_prompt_tokens == 120_000


@pytest.mark.usefixtures("ollama")
def test_ollama_prompt_budget_leaves_the_answer_room_in_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_NOTES__LLM__NUM_CTX", "32768")
    monkeypatch.setenv("WHADIO_NOTES__MAX_OUTPUT_TOKENS", "4096")

    # Act
    settings = load_notes_worker_settings()

    # Assert
    assert settings.notes.max_prompt_tokens == 28_672


@pytest.mark.usefixtures("ollama")
def test_ollama_prompt_budget_keeps_a_smaller_input_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_NOTES__MAX_INPUT_TOKENS", "8000")

    # Act
    settings = load_notes_worker_settings()

    # Assert
    assert settings.notes.max_prompt_tokens == 8_000


@pytest.mark.parametrize(
    ("field", "value", "refused"),
    [
        pytest.param("max_output_tokens", 1_023, True, id="max-output-bva-below-min"),
        pytest.param("max_output_tokens", 1_024, False, id="max-output-bva-min"),
        pytest.param("max_output_tokens", 1_025, False, id="max-output-bva-above-min"),
        pytest.param("max_input_tokens", 999, True, id="max-input-bva-below-min"),
        pytest.param("max_input_tokens", 1_000, False, id="max-input-bva-min"),
        pytest.param("max_input_tokens", 1_001, False, id="max-input-bva-above-min"),
        pytest.param("concurrency", 0, True, id="concurrency-bva-below-min"),
        pytest.param("concurrency", 1, False, id="concurrency-bva-min"),
        pytest.param("concurrency", 2, False, id="concurrency-bva-above-min"),
        pytest.param(
            "chars_per_token", math.nextafter(0.25, 0), True, id="chars-per-token-bva-below-min"
        ),
        pytest.param("chars_per_token", 0.25, False, id="chars-per-token-bva-min"),
        pytest.param(
            "chars_per_token", math.nextafter(0.25, 1), False, id="chars-per-token-bva-above-min"
        ),
    ],
)
def test_notes_limit_is_refused_only_below_its_floor(
    field: str, value: float, *, refused: bool
) -> None:
    # Act
    found = refused_fields(NotesSettings, {field: value})

    # Assert
    assert found == ({field} if refused else set[str]())


def test_infinite_chars_per_token_is_refused() -> None:
    # Act
    found = refused_fields(NotesSettings, {"chars_per_token": math.inf})

    # Assert
    assert found == {"chars_per_token"}


@pytest.mark.parametrize(
    ("field", "value", "refused"),
    [
        pytest.param("num_ctx", 2_047, True, id="num-ctx-bva-below-min"),
        pytest.param("num_ctx", 2_048, False, id="num-ctx-bva-min"),
        pytest.param("num_ctx", 2_049, False, id="num-ctx-bva-above-min"),
        pytest.param("keep_alive", -_MICROSECOND, True, id="keep-alive-bva-below-min"),
        pytest.param("keep_alive", 0.0, False, id="keep-alive-bva-min"),
        pytest.param("keep_alive", _MICROSECOND, False, id="keep-alive-bva-above-min"),
    ],
)
def test_ollama_limit_is_refused_only_below_its_floor(
    field: str, value: float, *, refused: bool
) -> None:
    # Act
    found = refused_fields(
        OllamaSettings, {"provider": "ollama", "model": "gemma3:12b", field: value}
    )

    # Assert
    assert found == ({field} if refused else set[str]())
