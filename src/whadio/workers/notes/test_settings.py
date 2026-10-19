from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from .settings import AnthropicSettings, OllamaSettings, load_notes_worker_settings


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WHADIO_BROKER__URL", "amqp://notes:secret@localhost:5672/whadio")
    monkeypatch.setenv("WHADIO_NOTES__LLM__API_KEY", "sk-ant-test")


@pytest.fixture
def ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WHADIO_NOTES__LLM__API_KEY")
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


def test_settings_read_the_dotenv_file_of_the_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    monkeypatch.delenv("WHADIO_NOTES__LLM__API_KEY")
    (tmp_path / ".env").write_text(
        "WHADIO_NOTES__LLM__API_KEY=sk-ant-from-file\n", encoding="utf-8"
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


def test_anthropic_is_the_provider_when_none_is_named() -> None:
    # Act
    settings = load_notes_worker_settings()

    # Assert
    assert isinstance(settings.notes.llm, AnthropicSettings)


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
    monkeypatch.delenv("WHADIO_NOTES__LLM__API_KEY")
    monkeypatch.setenv("WHADIO_NOTES__LLM__PROVIDER", "anthropic")

    # Act / Assert
    with pytest.raises(ValidationError, match="api_key"):
        load_notes_worker_settings()


@pytest.mark.usefixtures("ollama")
def test_ollama_settings_without_a_model_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.delenv("WHADIO_NOTES__LLM__MODEL")

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
