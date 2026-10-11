from enum import StrEnum


class CaptureStatus(StrEnum):
    RECORDING = "recording"
    IDLE = "idle"
    ASSEMBLED = "assembled"
    ABANDONED = "abandoned"
