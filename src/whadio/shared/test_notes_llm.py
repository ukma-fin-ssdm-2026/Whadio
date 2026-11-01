from pathlib import Path

import pytest
from pydantic import ValidationError

from .notes_llm import AnthropicLlm, OllamaLlm, load_notes_llm

API_KEY = "sk-ant-must-stay-hidden"


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("PROVIDER", "MODEL", "API_KEY"):
        monkeypatch.delenv(f"WHADIO_NOTES__LLM__{name}", raising=False)


def test_built_in_model_is_reported_as_whadio(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_NOTES__LLM__PROVIDER", "ollama")
    monkeypatch.setenv("WHADIO_NOTES__LLM__MODEL", "gemma4:12b-it-qat")
    # Act
    llm = load_notes_llm()
    # Assert
    assert (llm.reported_provider, llm.model) == ("whadio", "gemma4:12b-it-qat")


def test_claude_is_reported_as_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_NOTES__LLM__PROVIDER", "anthropic")
    monkeypatch.setenv("WHADIO_NOTES__LLM__MODEL", "claude-test")
    # Act
    llm = load_notes_llm()
    # Assert
    assert (llm.reported_provider, llm.model) == ("anthropic", "claude-test")


def test_claude_without_a_model_uses_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_NOTES__LLM__PROVIDER", "anthropic")
    # Act
    llm = load_notes_llm()
    # Assert
    assert llm == AnthropicLlm()


def test_claude_with_an_empty_model_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_NOTES__LLM__PROVIDER", "anthropic")
    monkeypatch.setenv("WHADIO_NOTES__LLM__MODEL", "")
    # Act / Assert
    with pytest.raises(ValidationError, match="model"):
        load_notes_llm()


def test_ollama_without_a_model_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_NOTES__LLM__PROVIDER", "ollama")
    # Act / Assert
    with pytest.raises(ValidationError, match="model"):
        load_notes_llm()


def test_settings_without_a_provider_are_refused() -> None:
    # Act / Assert
    with pytest.raises(ValidationError, match="notes"):
        load_notes_llm()


def test_unknown_provider_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_NOTES__LLM__PROVIDER", "olama")
    # Act / Assert
    with pytest.raises(ValidationError, match="union_tag_invalid"):
        load_notes_llm()


@pytest.mark.parametrize("provider", [None, "olama"], ids=["no-provider", "unknown-provider"])
def test_refusal_does_not_show_the_api_key(
    monkeypatch: pytest.MonkeyPatch, provider: str | None
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_NOTES__LLM__API_KEY", API_KEY)
    if provider is not None:
        monkeypatch.setenv("WHADIO_NOTES__LLM__PROVIDER", provider)
    # Act
    with pytest.raises(ValidationError) as failure:
        load_notes_llm()
    # Assert
    assert API_KEY not in str(failure.value)


def test_loaded_model_holds_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_NOTES__LLM__PROVIDER", "anthropic")
    monkeypatch.setenv("WHADIO_NOTES__LLM__API_KEY", API_KEY)
    # Act
    llm = load_notes_llm()
    # Assert
    assert API_KEY not in repr(llm.model_dump())


def test_other_notes_settings_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_NOTES__LLM__PROVIDER", "ollama")
    monkeypatch.setenv("WHADIO_NOTES__LLM__MODEL", "gemma4:12b-it-qat")
    monkeypatch.setenv("WHADIO_NOTES__LLM__BASE_URL", "http://ollama:11434")
    monkeypatch.setenv("WHADIO_NOTES__CONCURRENCY", "1")
    # Act
    llm = load_notes_llm()
    # Assert
    assert llm == OllamaLlm(provider="ollama", model="gemma4:12b-it-qat")
