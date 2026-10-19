from dataclasses import dataclass
from datetime import UTC
from enum import StrEnum
from typing import ClassVar, Final, Literal, assert_never
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl


class NoticeKind(StrEnum):
    SHARE_ACCESS_REQUEST = "share_access_request"
    RECORDING_DELETION_WARNING = "recording_deletion_warning"
    HOSTED_EVICTION = "hosted_eviction"
    PROCESSING_FINISHED = "processing_finished"
    PROCESSING_FAILED = "processing_failed"


class Locale(StrEnum):
    ENGLISH = "en"


# Notices hold metadata only; refusing unknown fields keeps meeting content out (threat model R-11).
_NOTICE_CONFIG: Final = ConfigDict(frozen=True, extra="forbid")


class ShareAccessRequest(BaseModel):
    model_config: ClassVar[ConfigDict] = _NOTICE_CONFIG

    kind: Literal[NoticeKind.SHARE_ACCESS_REQUEST] = Field(
        default=NoticeKind.SHARE_ACCESS_REQUEST, description="Kind of the notice"
    )
    share_id: UUID = Field(description="Share the access is requested through")
    requester_name: str = Field(min_length=1, description="Display name of the requesting account")
    requester_email: str = Field(min_length=1, description="Email of the requesting account")


class RecordingDeletionWarning(BaseModel):
    model_config: ClassVar[ConfigDict] = _NOTICE_CONFIG

    kind: Literal[NoticeKind.RECORDING_DELETION_WARNING] = Field(
        default=NoticeKind.RECORDING_DELETION_WARNING, description="Kind of the notice"
    )
    meeting_id: UUID = Field(description="Meeting whose recording is deleted")
    meeting_name: str = Field(min_length=1, description="Name of the meeting")
    deletes_at: AwareDatetime = Field(description="When the recording is deleted")


class HostedEviction(BaseModel):
    model_config: ClassVar[ConfigDict] = _NOTICE_CONFIG

    kind: Literal[NoticeKind.HOSTED_EVICTION] = Field(
        default=NoticeKind.HOSTED_EVICTION, description="Kind of the notice"
    )
    meeting_name: str | None = Field(
        description="Name of the deleted meeting; None when the recipient could not read it "
        "immediately before the deletion (NFR-003)"
    )


class ProcessingFinished(BaseModel):
    model_config: ClassVar[ConfigDict] = _NOTICE_CONFIG

    kind: Literal[NoticeKind.PROCESSING_FINISHED] = Field(
        default=NoticeKind.PROCESSING_FINISHED, description="Kind of the notice"
    )
    meeting_id: UUID = Field(description="Meeting that was processed")
    meeting_name: str = Field(min_length=1, description="Name of the meeting")


class ProcessingFailed(BaseModel):
    model_config: ClassVar[ConfigDict] = _NOTICE_CONFIG

    kind: Literal[NoticeKind.PROCESSING_FAILED] = Field(
        default=NoticeKind.PROCESSING_FAILED, description="Kind of the notice"
    )
    meeting_id: UUID = Field(description="Meeting whose processing finally failed")
    meeting_name: str = Field(min_length=1, description="Name of the meeting")


type Notice = (
    ShareAccessRequest
    | RecordingDeletionWarning
    | HostedEviction
    | ProcessingFinished
    | ProcessingFailed
)


@dataclass(frozen=True, slots=True)
class MailContent:
    subject: str
    body: str


@dataclass(frozen=True, slots=True)
class AppLinks:
    public_url: HttpUrl

    def meeting(self, meeting_id: UUID) -> str:
        return f"{self._base}/meetings/{meeting_id}"

    def meetings(self) -> str:
        return f"{self._base}/meetings"

    def share_access_requests(self, share_id: UUID) -> str:
        return f"{self._base}/shares/{share_id}/access-requests"

    @property
    def _base(self) -> str:
        return str(self.public_url).rstrip("/")


def render(notice: Notice, links: AppLinks, locale: Locale) -> MailContent:
    match locale:
        case Locale.ENGLISH:
            return _render_english(notice, links)
        case _:
            assert_never(locale)


def _render_english(notice: Notice, links: AppLinks) -> MailContent:
    match notice:
        case ShareAccessRequest():
            return MailContent(
                subject="Access request for a meeting you shared",
                body=(
                    f"{notice.requester_name} <{notice.requester_email}> asked for access to a "
                    "meeting you shared by link. Until you approve the request, they see none "
                    "of the meeting.\n\n"
                    f"Approve or decline it: {links.share_access_requests(notice.share_id)}\n"
                ),
            )
        case RecordingDeletionWarning():
            name = _one_line(notice.meeting_name)
            deletes_at = notice.deletes_at.astimezone(UTC)
            return MailContent(
                subject=f"The recording of “{name}” will be deleted on {deletes_at:%Y-%m-%d}",
                body=(
                    f"The recording of the meeting “{name}” will be deleted on "
                    f"{deletes_at:%Y-%m-%d} at {deletes_at:%H:%M} UTC. Its transcript and notes "
                    "are kept.\n\n"
                    f"Open the meeting: {links.meeting(notice.meeting_id)}\n"
                ),
            )
        case HostedEviction():
            return _english_eviction(notice.meeting_name, links)
        case ProcessingFinished():
            name = _one_line(notice.meeting_name)
            return MailContent(
                subject=f"“{name}” is ready",
                body=(
                    f"The meeting “{name}” has been processed; its transcript and notes are "
                    "ready.\n\n"
                    f"Open the meeting: {links.meeting(notice.meeting_id)}\n"
                ),
            )
        case ProcessingFailed():
            name = _one_line(notice.meeting_name)
            return MailContent(
                subject=f"Processing failed for “{name}”",
                body=(
                    f"Whadio could not process the meeting “{name}”.\n\n"
                    f"Open the meeting for details: {links.meeting(notice.meeting_id)}\n"
                ),
            )
        case _:
            assert_never(notice)


def _english_eviction(meeting_name: str | None, links: AppLinks) -> MailContent:
    if meeting_name is None:
        subject = "A meeting was deleted to stay within the meeting limit"
        deleted = "A meeting was deleted"
    else:
        name = _one_line(meeting_name)
        subject = f"“{name}” was deleted to stay within the meeting limit"
        deleted = f"The meeting “{name}” was deleted"
    return MailContent(
        subject=subject,
        body=(
            f"{deleted} because the workspaces of its owner reached their meeting limit. When a "
            "new meeting would exceed the limit, the earliest created one is deleted.\n\n"
            f"Your meetings: {links.meetings()}\n"
        ),
    )


def _one_line(text: str) -> str:
    return " ".join(text.split())
