from enum import StrEnum
from typing import Annotated
from uuid import UUID

from fastapi import Path
from pydantic import Field

from ..core.schemas import Input, Output

CAPTURE_ID_EXAMPLE = "3c2b1a09-8f7e-4d6c-b5a4-93827160f5e4"

CaptureId = Annotated[UUID, Path(description="Capture identifier", examples=[CAPTURE_ID_EXAMPLE])]
ChunkSeq = Annotated[
    int, Path(ge=0, le=1_000_000, description="Chunk number, from 0 in recording order")
]


class CaptureStatus(StrEnum):
    RECORDING = "recording"
    IDLE = "idle"
    ASSEMBLED = "assembled"
    ABANDONED = "abandoned"


class FolderOption(Output):
    id: UUID = Field(description="Folder identifier")
    name: str = Field(description="Folder name")
    is_default: bool = Field(description="The workspace's default folder")


class DestinationRead(Output):
    workspace_id: UUID = Field(description="Workspace identifier")
    name: str = Field(description="Workspace name")
    is_personal: bool = Field(
        description="The caller's personal workspace, used when no destination is chosen"
    )
    folders: list[FolderOption] = Field(description="Folders a recording can be filed in")


class CaptureCreate(Input):
    workspace_id: UUID | None = Field(
        default=None,
        strict=False,
        description="Destination workspace; the caller's personal workspace when omitted",
    )
    folder_id: UUID | None = Field(
        default=None,
        strict=False,
        description="Destination folder of that workspace; its default folder when omitted",
    )
    consent_confirmed: bool = Field(
        strict=True,
        description="The recorder confirms the participants agreed to be recorded; must be `true`",
    )


class CaptureComplete(Input):
    last_seq: int = Field(
        strict=True, ge=0, le=1_000_000, description="Number of the last chunk of the recording"
    )


class SpeakerEventInput(Input):
    at_seconds: float = Field(
        strict=True, ge=0, description="Seconds from the start of the recording"
    )
    speakers: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        max_length=100, description="Names of the participants speaking at that moment"
    )


class CaptureRead(Output):
    id: UUID = Field(description="Capture identifier")
    meeting_id: UUID = Field(description="The meeting the recording becomes")
    status: CaptureStatus = Field(
        description="`recording` while chunks are accepted; `assembled` once completed"
    )
    received_seqs: list[int] = Field(description="Numbers of the chunks stored so far, ascending")
    max_chunk_bytes: int = Field(description="Largest chunk the server accepts, in bytes")
