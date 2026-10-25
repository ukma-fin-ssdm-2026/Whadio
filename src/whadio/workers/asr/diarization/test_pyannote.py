from typing import Self, override

import pytest
import torch
from pyannote.audio import Pipeline
from pyannote.audio.pipelines.speaker_diarization import SpeakerDiarization

from .device import DeviceUnavailableError, DiarizationDevice
from .pyannote import load_pyannote


class _StandInPipeline(SpeakerDiarization):
    def __init__(self) -> None:
        # Skips SpeakerDiarization's constructor, which loads the segmentation and embedding models.
        Pipeline.__init__(self)
        self.devices: list[torch.device] = []

    @override
    def to(self, device: torch.device) -> Self:
        self.devices.append(device)
        return self


@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_pipeline_is_moved_to_the_configured_device(
    monkeypatch: pytest.MonkeyPatch, device: DiarizationDevice
) -> None:
    # Arrange
    pipeline = _StandInPipeline()

    def from_pretrained(_model: str, **_options: str | None) -> _StandInPipeline:
        return pipeline

    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(Pipeline, "from_pretrained", from_pretrained)

    # Act
    load_pyannote("pyannote/test", token=None, embedding_batch_size=8, device=device)

    # Assert
    assert pipeline.devices == [torch.device(device)]


def test_cuda_without_a_gpu_is_refused_before_the_model_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    downloads: list[str] = []

    def from_pretrained(model: str, **_options: str | None) -> None:
        downloads.append(model)

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(Pipeline, "from_pretrained", from_pretrained)

    # Act
    with pytest.raises(DeviceUnavailableError):
        load_pyannote("pyannote/test", token=None, embedding_batch_size=8, device="cuda")

    # Assert
    assert downloads == []
