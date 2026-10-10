import torch
from pyannote.audio import Pipeline
from pyannote.audio.pipelines.speaker_diarization import DiarizeOutput, SpeakerDiarization
from pyannote.audio.telemetry import set_telemetry_metrics

from ..audio import SAMPLE_RATE, Audio
from . import SpeakerTurn


class PyannoteDiarizer:
    def __init__(self, pipeline: SpeakerDiarization) -> None:
        self._pipeline: SpeakerDiarization = pipeline

    def diarize(self, audio: Audio) -> tuple[SpeakerTurn, ...]:
        waveform = torch.as_tensor(audio.samples).unsqueeze(0)
        output = self._pipeline({"waveform": waveform, "sample_rate": SAMPLE_RATE})
        if not isinstance(output, DiarizeOutput):
            raise TypeError("the diarization pipeline runs in legacy mode")
        # The exclusive variant leaves out overlapped speech, so every word has one speaker.
        return tuple(
            SpeakerTurn(start=segment.start, end=segment.end, speaker=str(label))
            for segment, label in output.exclusive_speaker_diarization
        )


def load_pyannote(model: str, *, token: str | None, embedding_batch_size: int) -> PyannoteDiarizer:
    # pyannote.audio 4 sends usage telemetry to otel.pyannote.ai unless it is switched off.
    set_telemetry_metrics(enabled=False)
    pipeline = Pipeline.from_pretrained(model, token=token)
    if not isinstance(pipeline, SpeakerDiarization):
        raise TypeError(f"{model} is not a speaker diarization pipeline")
    pipeline.embedding_batch_size = embedding_batch_size
    return PyannoteDiarizer(pipeline)
