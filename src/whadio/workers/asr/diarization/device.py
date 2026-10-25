from typing import Literal

type DiarizationDevice = Literal["cpu", "cuda"]


class DeviceUnavailableError(Exception):
    pass


def require_device(device: DiarizationDevice, *, cuda_available: bool) -> None:
    # Falling back to the CPU would hide a misconfigured GPU host behind much slower jobs.
    if device == "cuda" and not cuda_available:
        raise DeviceUnavailableError(
            "Diarization is set to run on cuda, but torch finds no CUDA device: install the cuda "
            "extra and give the worker an NVIDIA GPU, or set WHADIO_ASR__DIARIZATION__DEVICE=cpu"
        )
