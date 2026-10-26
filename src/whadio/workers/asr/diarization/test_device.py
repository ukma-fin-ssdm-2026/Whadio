import pytest

from .device import DeviceUnavailableError, DiarizationDevice, require_device


def _refused(device: DiarizationDevice, *, cuda_available: bool) -> bool:
    try:
        require_device(device, cuda_available=cuda_available)
    except DeviceUnavailableError:
        return True
    return False


@pytest.mark.parametrize(
    ("device", "cuda_available", "refused"),
    [
        pytest.param("cpu", False, False, id="cpu-without-gpu"),
        pytest.param("cpu", True, False, id="cpu-with-gpu"),
        pytest.param("cuda", True, False, id="cuda-with-gpu"),
        pytest.param("cuda", False, True, id="cuda-without-gpu"),
    ],
)
def test_device_is_refused_only_when_cuda_is_asked_for_without_a_gpu(
    device: DiarizationDevice, *, cuda_available: bool, refused: bool
) -> None:
    # Act
    found = _refused(device, cuda_available=cuda_available)

    # Assert
    assert found is refused
