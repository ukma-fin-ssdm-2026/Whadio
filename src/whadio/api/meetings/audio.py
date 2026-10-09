from typing import BinaryIO, Final

import av
from av.error import FFmpegError

SUPPORTED_FORMATS: Final = "WAV, MP3, AAC, FLAC, Ogg, WebM or MP4/M4A"
_DEMUXERS: Final = frozenset(
    {"wav", "mp3", "aac", "flac", "ogg", "matroska,webm", "mov,mp4,m4a,3gp,3g2,mj2"}
)


def is_supported_audio(recording: BinaryIO) -> bool:
    """Whether FFmpeg opens `recording` as a supported format and decodes its first audio frame."""
    try:
        with av.open(recording, mode="r") as container:
            if container.format.name not in _DEMUXERS or not container.streams.audio:
                return False
            return next(container.decode(audio=0), None) is not None
    except FFmpegError:
        return False
