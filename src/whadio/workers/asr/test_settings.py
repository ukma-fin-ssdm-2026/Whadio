from pathlib import Path

import pytest
from pydantic import JsonValue, ValidationError

from conftest import refused_fields

from .recognition import RecognizerKind
from .settings import AsrSettings, load_asr_worker_settings


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WHADIO_BROKER__URL", "amqp://asr:secret@localhost:5672/whadio")


def test_settings_default_to_the_parakeet_recognizer() -> None:
    # Act
    settings = load_asr_worker_settings()

    # Assert
    assert settings.asr.recognizer is RecognizerKind.PARAKEET


def test_settings_default_to_diarization_on_the_cpu() -> None:
    # Act
    settings = load_asr_worker_settings()

    # Assert
    assert settings.asr.diarization.device == "cpu"


def test_settings_read_nested_model_variables_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_ASR__RECOGNIZER", "whisper")
    monkeypatch.setenv("WHADIO_ASR__WHISPER__MODEL", "medium")

    # Act
    settings = load_asr_worker_settings()

    # Assert
    assert (settings.asr.recognizer, settings.asr.whisper.model) == (
        RecognizerKind.WHISPER,
        "medium",
    )


def test_settings_read_the_hugging_face_token_from_the_dotenv_file(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / ".env").write_text(
        "WHADIO_ASR__DIARIZATION__HF_TOKEN=from-the-file\n", encoding="utf-8"
    )

    # Act
    settings = load_asr_worker_settings()

    # Assert
    token = settings.asr.diarization.hf_token
    assert token is not None
    assert token.get_secret_value() == "from-the-file"


def test_settings_read_the_candidate_languages_as_a_json_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_ASR__LANGUAGES", '["uk", "en"]')

    # Act
    settings = load_asr_worker_settings()

    # Assert
    assert settings.asr.languages == ("uk", "en")


def test_settings_with_a_single_candidate_language_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_ASR__LANGUAGES", '["uk"]')

    # Act / Assert
    with pytest.raises(ValidationError, match="languages"):
        load_asr_worker_settings()


def test_settings_with_an_unknown_recognizer_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_ASR__RECOGNIZER", "kaldi")

    # Act / Assert
    with pytest.raises(ValidationError, match="recognizer"):
        load_asr_worker_settings()


def test_settings_with_an_unknown_diarization_device_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_ASR__DIARIZATION__DEVICE", "mps")

    # Act / Assert
    with pytest.raises(ValidationError, match="device"):
        load_asr_worker_settings()


@pytest.mark.parametrize(
    ("data", "refused"),
    [
        pytest.param({"whisper": {"beam_size": 0}}, {"whisper.beam_size"}, id="beam-bva-below-min"),
        pytest.param({"whisper": {"beam_size": 1}}, set[str](), id="beam-bva-min"),
        pytest.param({"whisper": {"beam_size": 2}}, set[str](), id="beam-bva-above-min"),
        pytest.param(
            {"diarization": {"embedding_batch_size": 0}},
            {"diarization.embedding_batch_size"},
            id="embedding-batch-bva-below-min",
        ),
        pytest.param(
            {"diarization": {"embedding_batch_size": 1}}, set[str](), id="embedding-batch-bva-min"
        ),
        pytest.param(
            {"diarization": {"embedding_batch_size": 2}},
            set[str](),
            id="embedding-batch-bva-above-min",
        ),
        pytest.param({"max_audio_bytes": 0}, {"max_audio_bytes"}, id="audio-bytes-bva-below-min"),
        pytest.param({"max_audio_bytes": 1}, set[str](), id="audio-bytes-bva-min"),
        pytest.param({"max_audio_bytes": 2}, set[str](), id="audio-bytes-bva-above-min"),
        pytest.param({"slots": 0}, {"slots"}, id="slots-bva-below-min"),
        pytest.param({"slots": 1}, set[str](), id="slots-bva-min"),
        pytest.param({"slots": 2}, set[str](), id="slots-bva-above-min"),
        pytest.param({"languages": ["uk", "en"]}, set[str](), id="languages-bva-min"),
        pytest.param({"languages": ["uk", "en", "pl"]}, set[str](), id="languages-bva-above-min"),
    ],
)
def test_asr_limit_is_refused_only_below_its_floor(
    data: dict[str, JsonValue], refused: set[str]
) -> None:
    # Act
    found = refused_fields(AsrSettings, data)

    # Assert
    assert found == refused
