from typing import Final

SNIFF_BYTES: Final = 12
SUPPORTED_FORMATS: Final = "WAV, MP3, AAC, FLAC, Ogg, WebM or MP4/M4A"


def is_supported_audio(head: bytes) -> bool:
    """Recognise a supported container by its signature in the first `SNIFF_BYTES` bytes."""
    return (
        head.startswith((b"ID3", b"fLaC", b"OggS", b"\x1a\x45\xdf\xa3"))
        or (head.startswith(b"RIFF") and head[8:12] == b"WAVE")
        or head[4:8] == b"ftyp"
        or (len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0)
    )
