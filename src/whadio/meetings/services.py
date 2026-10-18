import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from ..access_policy.contracts import MeetingScope
from ..access_policy.services import ContentPath, IMeetingPolicy
from ..accounts.enums import WorkspaceRole
from ..accounts.services import IWorkspaceMembership
from ..audit.contracts import ContentEvent, IContentAuditWriter
from ..audit.enums import AuditAction
from ..audit.services import IAuditWriter, MeetingMoved
from ..shared.errors import Failure, UseCaseError
from ..shared.pagination import ListWindow
from .contracts import (
    ContextTranscript,
    InitialTranscript,
    MeetingFilter,
    NoteVersion,
    PipelineMeeting,
    ProcessingUpdate,
    TranscriptVersion,
)
from .enums import AccessMode, MeetingSource, ProcessingState, RecordingStatus, RevisionType
from .models import (
    Folder,
    GlossaryTerm,
    Meeting,
    Note,
    Speaker,
    Transcript,
    TranscriptRevision,
    TranscriptSegment,
)
from .repositories import (
    IFolderRepository,
    IMeetingRepository,
)


@dataclass(frozen=True)
class TranscriptEdit:
    base_revision_id: UUID
    text_changes: dict[UUID, str]
    speaker_changes: dict[UUID, str]


@dataclass(frozen=True)
class TermUpdate:
    term: str | None = None
    preferred_form: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class RecordingInput:
    # None only for an extension capture, whose recording is attached once it is assembled.
    storage_key: str | None
    recorded_at: datetime
    source: MeetingSource
    duration_seconds: int | None = None
    name: str | None = None
    folder_id: UUID | None = None
    consent_confirmed_at: datetime | None = None


class IRecordingIngestion(Protocol):
    async def create(
        self, actor_id: UUID, workspace_id: UUID, recording: RecordingInput, now: datetime
    ) -> Meeting:
        """Persist verified recording metadata; Capture or Processing queues work separately."""
        ...


class MeetingService:
    def __init__(
        self, repository: IMeetingRepository, policy: IMeetingPolicy, audit: IContentAuditWriter
    ) -> None:
        self._repository: IMeetingRepository = repository
        self._policy: IMeetingPolicy = policy
        self._audit: IContentAuditWriter = audit

    async def create(
        self, actor_id: UUID, workspace_id: UUID, recording: RecordingInput, now: datetime
    ) -> Meeting:
        await self._policy.workspace_role(workspace_id, actor_id)
        if (
            recording.storage_key == ""
            or (recording.storage_key is None and recording.source != MeetingSource.EXTENSION)
            or recording.recorded_at.tzinfo is None
            or recording.recorded_at.utcoffset() is None
            or (recording.duration_seconds is not None and recording.duration_seconds <= 0)
            or (
                recording.source == MeetingSource.EXTENSION
                and (
                    recording.consent_confirmed_at is None
                    or recording.consent_confirmed_at.utcoffset() is None
                )
            )
        ):
            raise UseCaseError(Failure.VALIDATION_ERROR)
        if recording.folder_id is None:
            folder = next(
                item for item in await self._repository.folders(workspace_id) if item.is_default
            )
        else:
            try:
                folder = await self._repository.folder(workspace_id, recording.folder_id)
            except UseCaseError as error:
                if error.code == Failure.NOT_FOUND:
                    raise UseCaseError(Failure.VALIDATION_ERROR) from None
                raise
        meeting = Meeting(
            meeting_id=uuid4(),
            folder_id=folder.folder_id,
            created_by_user_id=actor_id,
            name=self._name(recording.name)
            if recording.name is not None
            else recording.recorded_at.isoformat(),
            name_is_generated=recording.name is None,
            source_type=recording.source,
            recording_status=RecordingStatus.COMPLETE,
            processing_state=ProcessingState.RECORDING
            if recording.storage_key is None
            else ProcessingState.QUEUED,
            storage_path=recording.storage_key,
            recorded_at=recording.recorded_at,
            created_at=now,
            duration_seconds=recording.duration_seconds,
            recording_delete_after=recording.recorded_at + timedelta(days=90),
            access_mode=AccessMode.WORKSPACE,
            consent_confirmed_at=recording.consent_confirmed_at
            if recording.source == MeetingSource.EXTENSION
            else None,
            consent_confirmed_by_user_id=actor_id
            if recording.source == MeetingSource.EXTENSION
            else None,
        )
        await self._repository.save(meeting)
        await self._audit.write(
            ContentEvent(
                actor_id, workspace_id, meeting.meeting_id, AuditAction.MEETING_CREATED, now
            )
        )
        return meeting

    async def get(self, actor_id: UUID, meeting_id: UUID) -> Meeting:
        await self._authorize(actor_id, meeting_id)
        return await self._repository.get(meeting_id)

    async def workspace_id(self, actor_id: UUID, meeting_id: UUID) -> UUID:
        return (await self._authorize(actor_id, meeting_id)).workspace_id

    async def delete(self, actor_id: UUID, meeting_id: UUID, now: datetime) -> None:
        scope = await self._authorize(actor_id, meeting_id, lock=True)
        permission = await self._policy.authorize(scope, actor_id)
        if scope.creator_id != actor_id and (
            permission.role is None
            or permission.role not in (WorkspaceRole.OWNER, WorkspaceRole.MODERATOR)
        ):
            raise UseCaseError(Failure.INSUFFICIENT_ROLE)
        await self._repository.remove(meeting_id, now)
        await self._audit.write(
            ContentEvent(actor_id, scope.workspace_id, meeting_id, AuditAction.MEETING_DELETED, now)
        )

    async def list_meetings(self, actor_id: UUID, filters: MeetingFilter) -> list[Meeting]:
        await self._policy.workspace_role(filters.workspace_id, actor_id)
        return await self._repository.visible(filters, self._policy.granted_meetings(actor_id))

    async def update(
        self,
        actor_id: UUID,
        meeting_id: UUID,
        now: datetime,
        *,
        name: str | None = None,
        folder_id: UUID | None = None,
    ) -> Meeting:
        if name is None and folder_id is None:
            raise UseCaseError(Failure.VALIDATION_ERROR)
        scope = await self._authorize(actor_id, meeting_id, lock=True)
        meeting = await self._repository.get(meeting_id)
        if folder_id is not None and folder_id != meeting.folder_id:
            try:
                await self._repository.folder(scope.workspace_id, folder_id)
            except UseCaseError as error:
                if error.code == Failure.NOT_FOUND:
                    raise UseCaseError(Failure.VALIDATION_ERROR) from None
                raise
            old_folder_id = meeting.folder_id
            meeting.folder_id = folder_id
            await self._repository.save(meeting)
            await self._audit.write(
                ContentEvent(
                    actor_id,
                    scope.workspace_id,
                    meeting_id,
                    AuditAction.MEETING_MOVED,
                    now,
                    from_folder_id=old_folder_id,
                    to_folder_id=folder_id,
                )
            )
        if name is not None:
            meeting.name = self._name(name)
            meeting.name_is_generated = False
            await self._repository.save(meeting)
            await self._audit.write(
                ContentEvent(
                    actor_id,
                    scope.workspace_id,
                    meeting_id,
                    AuditAction.MEETING_RENAMED,
                    now,
                )
            )
        return meeting

    async def folders(
        self, actor_id: UUID, workspace_id: UUID, page: ListWindow | None = None
    ) -> list[Folder]:
        await self._policy.workspace_role(workspace_id, actor_id)
        return await self._repository.folders(workspace_id, page)

    async def create_folder(
        self, actor_id: UUID, workspace_id: UUID, name: str, now: datetime
    ) -> Folder:
        await self._moderator(actor_id, workspace_id)
        folder = Folder(
            folder_id=uuid4(),
            workspace_id=workspace_id,
            name=self._name(name),
            created_at=now,
            is_default=False,
        )
        if await self._repository.folder_name_exists(workspace_id, folder.name, folder.folder_id):
            raise UseCaseError(Failure.FOLDER_EXISTS)
        await self._repository.save_folder(folder)
        return folder

    async def rename_folder(
        self, actor_id: UUID, workspace_id: UUID, folder_id: UUID, name: str
    ) -> Folder:
        await self._moderator(actor_id, workspace_id)
        folder = await self._repository.folder(workspace_id, folder_id, lock=True)
        name = self._name(name)
        if await self._repository.folder_name_exists(workspace_id, name, folder_id):
            raise UseCaseError(Failure.FOLDER_EXISTS)
        folder.name = name
        await self._repository.save_folder(folder)
        return folder

    async def transcript(
        self, actor_id: UUID, meeting_id: UUID, revision_id: UUID | None = None
    ) -> TranscriptVersion:
        await self._authorize(actor_id, meeting_id)
        return await self._repository.version(meeting_id, revision_id)

    async def revisions(
        self, actor_id: UUID, meeting_id: UUID, page: ListWindow | None = None
    ) -> list[TranscriptRevision]:
        await self._authorize(actor_id, meeting_id)
        await self._repository.version(meeting_id)
        return await self._repository.revisions(meeting_id, page)

    async def edit_transcript(
        self, actor_id: UUID, meeting_id: UUID, edit: TranscriptEdit, now: datetime
    ) -> TranscriptVersion:
        scope = await self._authorize(actor_id, meeting_id, lock=True)
        previous = await self._repository.version(meeting_id)
        if previous.revision.revision_id != edit.base_revision_id:
            raise UseCaseError(Failure.STALE_REVISION)
        if (
            (not edit.text_changes and not edit.speaker_changes)
            or not edit.text_changes.keys() <= {item.segment_id for item in previous.segments}
            or not edit.speaker_changes.keys() <= {item.speaker_id for item in previous.speakers}
        ):
            raise UseCaseError(Failure.VALIDATION_ERROR)
        revision = TranscriptRevision(
            revision_id=uuid4(),
            transcript_id=previous.transcript.transcript_id,
            revision_type=RevisionType.EDITED,
            edited_by_user_id=actor_id,
            created_at=now,
        )
        speaker_ids = {item.speaker_id: uuid4() for item in previous.speakers}
        speakers = [
            Speaker(
                speaker_id=speaker_ids[item.speaker_id],
                revision_id=revision.revision_id,
                display_name=self._name(
                    edit.speaker_changes.get(item.speaker_id, item.display_name)
                ),
            )
            for item in previous.speakers
        ]
        segments = [
            TranscriptSegment(
                segment_id=uuid4(),
                revision_id=revision.revision_id,
                speaker_id=None if item.speaker_id is None else speaker_ids[item.speaker_id],
                start_time_seconds=item.start_time_seconds,
                end_time_seconds=item.end_time_seconds,
                text=edit.text_changes.get(item.segment_id, item.text),
            )
            for item in previous.segments
        ]
        version = TranscriptVersion(
            previous.transcript,
            revision,
            previous.original_revision_id,
            is_edited=True,
            speakers=speakers,
            segments=segments,
        )
        await self._repository.save_version(version)
        if edit.text_changes:
            await self._audit.write(
                ContentEvent(
                    actor_id,
                    scope.workspace_id,
                    meeting_id,
                    AuditAction.TRANSCRIPT_EDITED,
                    now,
                    revision.revision_id,
                )
            )
        if edit.speaker_changes:
            await self._audit.write(
                ContentEvent(
                    actor_id,
                    scope.workspace_id,
                    meeting_id,
                    AuditAction.SPEAKER_RENAMED,
                    now,
                    revision.revision_id,
                )
            )
        return version

    async def notes(
        self, actor_id: UUID, meeting_id: UUID, page: ListWindow | None = None
    ) -> list[NoteVersion]:
        await self._authorize(actor_id, meeting_id)
        return await self._repository.notes(meeting_id, page)

    async def shared_transcript(
        self,
        actor_id: UUID,
        share_id: UUID,
        meeting_id: UUID,
        revision_id: UUID | None = None,
    ) -> TranscriptVersion:
        permission = await self._policy.authorize_share(share_id, actor_id, ContentPath.READ)
        if permission.meeting_id != meeting_id:
            raise UseCaseError(Failure.NOT_FOUND)
        version = await self._repository.version(meeting_id, revision_id)
        if not permission.redact_speaker_names:
            return version
        names = self._anonymous_names(version)
        return TranscriptVersion(
            version.transcript,
            version.revision,
            version.original_revision_id,
            version.is_edited,
            [
                Speaker(
                    speaker_id=item.speaker_id,
                    revision_id=item.revision_id,
                    display_name=names[item.speaker_id],
                )
                for item in version.speakers
            ],
            version.segments,
        )

    async def shared_notes(
        self, actor_id: UUID, share_id: UUID, meeting_id: UUID, page: ListWindow | None = None
    ) -> list[NoteVersion]:
        permission = await self._policy.authorize_share(share_id, actor_id, ContentPath.READ)
        if permission.meeting_id != meeting_id:
            raise UseCaseError(Failure.NOT_FOUND)
        versions = await self._repository.notes(meeting_id, page)
        if not permission.redact_speaker_names:
            return versions
        replacements: dict[str, str] = {}
        for revision in await self._repository.revisions(meeting_id):
            version = await self._repository.version(meeting_id, revision.revision_id)
            labels = self._anonymous_names(version)
            for speaker in version.speakers:
                label = labels[speaker.speaker_id]
                previous = replacements.get(speaker.display_name)
                replacements[speaker.display_name] = (
                    label if previous in (None, label) else "Speaker"
                )
        pattern = (
            re.compile(
                r"(?<!\w)(?:"
                + "|".join(re.escape(name) for name in sorted(replacements, key=len, reverse=True))
                + r")(?!\w)"
            )
            if replacements
            else None
        )
        return [
            NoteVersion(
                self._redacted_note(version, replacements, pattern),
                version.context,
                version.is_current,
            )
            for version in versions
        ]

    @staticmethod
    def _redacted_note(
        version: NoteVersion, names: dict[str, str], pattern: re.Pattern[str] | None
    ) -> Note:
        note = version.note
        return Note(
            note_id=note.note_id,
            meeting_id=note.meeting_id,
            template=note.template,
            provider=note.provider,
            model_name=note.model_name,
            created_at=note.created_at,
            created_by_user_id=note.created_by_user_id,
            content=note.content
            if pattern is None
            else pattern.sub(lambda match: names[match.group()], note.content),
        )

    async def glossary(
        self, actor_id: UUID, workspace_id: UUID, page: ListWindow | None = None
    ) -> list[GlossaryTerm]:
        await self._policy.workspace_role(workspace_id, actor_id)
        return await self._repository.glossary(workspace_id, page)

    async def add_term(self, actor_id: UUID, term: GlossaryTerm) -> GlossaryTerm:
        await self._policy.workspace_role(term.workspace_id, actor_id)
        term.term = self._name(term.term)
        if term.source_meeting_id is not None:
            scope = await self._authorize(actor_id, term.source_meeting_id)
            if scope.workspace_id != term.workspace_id:
                raise UseCaseError(Failure.NOT_FOUND)
        if any(
            item.term.lower() == term.term.lower()
            for item in await self._repository.glossary(term.workspace_id)
        ):
            raise UseCaseError(Failure.TERM_EXISTS)
        term.created_by_user_id = actor_id
        await self._repository.save_term(term)
        return term

    async def delete_term(self, actor_id: UUID, workspace_id: UUID, term_id: UUID) -> None:
        role = await self._policy.workspace_role(workspace_id, actor_id)
        term = await self._repository.term(workspace_id, term_id)
        if (
            role not in (WorkspaceRole.OWNER, WorkspaceRole.MODERATOR)
            and term.created_by_user_id != actor_id
        ):
            raise UseCaseError(Failure.INSUFFICIENT_ROLE)
        await self._repository.remove_term(term_id)

    async def update_term(
        self, actor_id: UUID, workspace_id: UUID, term_id: UUID, changes: TermUpdate
    ) -> GlossaryTerm:
        role = await self._policy.workspace_role(workspace_id, actor_id)
        term = await self._repository.term(workspace_id, term_id)
        if (
            role not in (WorkspaceRole.OWNER, WorkspaceRole.MODERATOR)
            and term.created_by_user_id != actor_id
        ):
            raise UseCaseError(Failure.INSUFFICIENT_ROLE)
        if changes.term is not None:
            new_term = self._name(changes.term)
            if any(
                item.term_id != term_id and item.term.lower() == new_term.lower()
                for item in await self._repository.glossary(workspace_id)
            ):
                raise UseCaseError(Failure.TERM_EXISTS)
            term.term = new_term
        if changes.preferred_form is not None:
            term.preferred_form = self._name(changes.preferred_form)
        if changes.description is not None:
            term.description = changes.description
        await self._repository.save_term(term)
        return term

    async def context(self, actor_id: UUID, meeting_id: UUID) -> list[TranscriptVersion]:
        scope = await self._authorize(actor_id, meeting_id)
        target = await self._repository.get(meeting_id)
        versions: list[TranscriptVersion] = []
        for meeting in await self.list_meetings(
            actor_id, MeetingFilter(scope.workspace_id, target.folder_id)
        ):
            if meeting.meeting_id == meeting_id or meeting.access_mode == "restricted":
                continue
            try:
                versions.append(await self.transcript(actor_id, meeting.meeting_id))
            except UseCaseError as error:
                if error.code != Failure.NOT_TRANSCRIBED:
                    raise
        return versions

    async def folder_count(self, actor_id: UUID, workspace_id: UUID, folder_id: UUID) -> int:
        await self._policy.workspace_role(workspace_id, actor_id)
        await self._repository.folder(workspace_id, folder_id)
        counts = await self._repository.folder_counts(
            workspace_id, [folder_id], self._policy.granted_meetings(actor_id)
        )
        return counts.get(folder_id, 0)

    async def folder_counts(
        self, actor_id: UUID, workspace_id: UUID, folder_ids: list[UUID]
    ) -> dict[UUID, int]:
        await self._policy.workspace_role(workspace_id, actor_id)
        return await self._repository.folder_counts(
            workspace_id, folder_ids, self._policy.granted_meetings(actor_id)
        )

    async def save_initial_transcript(
        self, meeting_id: UUID, result: InitialTranscript, now: datetime
    ) -> TranscriptVersion:
        """Persist an original result; replaying its job preserves the current revision."""
        await self._repository.get(meeting_id, lock=True)
        try:
            existing = await self._repository.version(meeting_id)
        except UseCaseError as error:
            if error.code != Failure.NOT_TRANSCRIBED:
                raise
        else:
            if existing.transcript.source_job_id != result.job_id:
                raise UseCaseError(Failure.TRANSCRIPT_EXISTS)
            return existing
        keys = {speaker.key for speaker in result.speakers}
        if (
            len(keys) != len(result.speakers)
            or any(not key for key in keys)
            or not result.language.strip()
            or not result.model_name.strip()
            or any(
                not segment.start_seconds.is_finite()
                or not segment.end_seconds.is_finite()
                or segment.start_seconds < 0
                or segment.end_seconds <= segment.start_seconds
                or (segment.speaker_key is not None and segment.speaker_key not in keys)
                for segment in result.segments
            )
        ):
            raise UseCaseError(Failure.VALIDATION_ERROR)
        transcript_id, revision_id = uuid4(), uuid4()
        transcript = Transcript(
            transcript_id=transcript_id,
            meeting_id=meeting_id,
            source_job_id=result.job_id,
            language=result.language,
            model_name=result.model_name,
            current_revision_id=revision_id,
            created_at=now,
        )
        revision = TranscriptRevision(
            revision_id=revision_id,
            transcript_id=transcript_id,
            revision_type=RevisionType.ORIGINAL,
            created_at=now,
        )
        speaker_ids = {speaker.key: uuid4() for speaker in result.speakers}
        speakers = [
            Speaker(
                speaker_id=speaker_ids[speaker.key],
                revision_id=revision_id,
                display_name=self._name(speaker.display_name),
            )
            for speaker in result.speakers
        ]
        segments = [
            TranscriptSegment(
                segment_id=uuid4(),
                revision_id=revision_id,
                speaker_id=None
                if segment.speaker_key is None
                else speaker_ids[segment.speaker_key],
                start_time_seconds=segment.start_seconds,
                end_time_seconds=segment.end_seconds,
                text=segment.text,
            )
            for segment in result.segments
        ]
        version = TranscriptVersion(
            transcript, revision, revision_id, is_edited=False, speakers=speakers, segments=segments
        )
        await self._repository.save_initial(version)
        return version

    async def processing_snapshot(self, actor_id: UUID, meeting_id: UUID) -> Meeting:
        """Processing locks before deciding whether to reserve a job and enforce its limits."""
        await self._authorize(actor_id, meeting_id, lock=True)
        return await self._repository.get(meeting_id)

    async def save_processing_state(self, meeting_id: UUID, update: ProcessingUpdate) -> None:
        """Persist Processing's decision without choosing transitions or enforcing job limits."""
        if (
            (update.state == ProcessingState.FAILED) != (update.failure is not None)
            or (update.regeneration_count is not None and update.regeneration_count < 0)
            or (update.duration_seconds is not None and update.duration_seconds < 0)
        ):
            raise UseCaseError(Failure.VALIDATION_ERROR)
        meeting = await self._repository.get(meeting_id, lock=True)
        meeting.processing_state = update.state
        meeting.failure_reason = update.failure
        if update.regeneration_count is not None:
            meeting.regeneration_count = update.regeneration_count
        if update.duration_seconds is not None:
            meeting.duration_seconds = update.duration_seconds
        await self._repository.save(meeting)

    async def attach_recording(
        self, meeting_id: UUID, storage_key: str, status: RecordingStatus
    ) -> None:
        """Give a meeting still being captured its assembled recording; MeetingPersistence has
        checked the caller and the capacity, and Capture queues it separately."""
        meeting = await self._repository.get(meeting_id, lock=True)
        if not storage_key or meeting.processing_state != ProcessingState.RECORDING:
            raise UseCaseError(Failure.VALIDATION_ERROR)
        meeting.storage_path = storage_key
        meeting.recording_status = status
        await self._repository.save(meeting)

    # --- For Processing, which acts for no member, so nothing here checks access ---

    async def pipeline_meeting(
        self, meeting_id: UUID, *, lock: bool = False
    ) -> PipelineMeeting | None:
        try:
            scope = await self._repository.scope(meeting_id, lock=lock)
        except UseCaseError as error:
            if error.code == Failure.NOT_FOUND:
                return None
            raise
        return PipelineMeeting(await self._repository.get(meeting_id), scope.workspace_id)

    async def current_transcript(self, meeting_id: UUID) -> TranscriptVersion | None:
        try:
            return await self._repository.version(meeting_id)
        except UseCaseError as error:
            if error.code == Failure.NOT_TRANSCRIBED:
                return None
            raise

    async def notes_context(self, meeting: Meeting, limit: int) -> list[ContextTranscript]:
        """Processed meetings of the same folder; a restricted one never reaches another
        meeting's notes (FR-019)."""
        context: list[ContextTranscript] = []
        # One extra row makes up for the meeting itself.
        for other in await self._repository.processed_in_folder(meeting.folder_id, limit + 1):
            transcript = (
                None
                if other.meeting_id == meeting.meeting_id
                else await self.current_transcript(other.meeting_id)
            )
            if transcript is not None:
                context.append(ContextTranscript(other, transcript))
        return context[:limit]

    async def workspace_glossary(self, workspace_id: UUID) -> list[GlossaryTerm]:
        return await self._repository.glossary(workspace_id)

    async def _authorize(
        self, actor_id: UUID, meeting_id: UUID, *, lock: bool = False
    ) -> MeetingScope:
        scope = await self._repository.scope(meeting_id, lock=lock)
        await self._policy.authorize(scope, actor_id)
        return scope

    async def _moderator(self, actor_id: UUID, workspace_id: UUID) -> None:
        role = await self._policy.workspace_role(workspace_id, actor_id)
        if role not in (WorkspaceRole.OWNER, WorkspaceRole.MODERATOR):
            raise UseCaseError(Failure.INSUFFICIENT_ROLE)

    @staticmethod
    def _name(value: str) -> str:
        value = value.strip()
        if not value or any(not char.isprintable() for char in value):
            raise UseCaseError(Failure.VALIDATION_ERROR)
        return value

    @staticmethod
    def _anonymous_names(version: TranscriptVersion) -> dict[UUID, str]:
        order = list(
            dict.fromkeys(
                item.speaker_id for item in version.segments if item.speaker_id is not None
            )
        )
        order.extend(item.speaker_id for item in version.speakers if item.speaker_id not in order)
        return {speaker_id: f"Speaker {index}" for index, speaker_id in enumerate(order, start=1)}


class FolderService:
    def __init__(
        self,
        repository: IFolderRepository,
        memberships: IWorkspaceMembership,
        audit: IAuditWriter,
    ) -> None:
        self._repository: IFolderRepository = repository
        self._memberships: IWorkspaceMembership = memberships
        self._audit: IAuditWriter = audit

    async def delete_folder(
        self, actor_id: UUID, workspace_id: UUID, folder_id: UUID, now: datetime
    ) -> None:
        """Move, audit and delete using collaborators sharing the caller's transaction."""
        role = await self._memberships.lock_role(workspace_id, actor_id)
        if role is None:
            raise UseCaseError(Failure.NOT_FOUND)
        if role not in (WorkspaceRole.OWNER, WorkspaceRole.MODERATOR):
            raise UseCaseError(Failure.INSUFFICIENT_ROLE)
        folder = await self._repository.folder(workspace_id, folder_id)
        if folder is None:
            raise UseCaseError(Failure.NOT_FOUND)
        if folder.is_default:
            raise UseCaseError(Failure.DEFAULT_FOLDER)
        destination = await self._repository.default_folder(workspace_id)
        if destination is None:
            raise UseCaseError(Failure.NOT_FOUND)
        meeting_ids = await self._repository.move_meetings(folder_id, destination.folder_id)
        await self._repository.remember(folder, meeting_ids, now)
        for meeting_id in meeting_ids:
            await self._audit.write(
                MeetingMoved(
                    actor_id,
                    workspace_id,
                    meeting_id,
                    now,
                    folder_id,
                    destination.folder_id,
                )
            )
        await self._repository.remove_folder(folder_id)

    async def restore_folder(
        self, actor_id: UUID, workspace_id: UUID, folder_id: UUID, now: datetime
    ) -> Folder:
        role = await self._memberships.lock_role(workspace_id, actor_id)
        if role is None:
            raise UseCaseError(Failure.NOT_FOUND)
        if role not in (WorkspaceRole.OWNER, WorkspaceRole.MODERATOR):
            raise UseCaseError(Failure.INSUFFICIENT_ROLE)
        destination = await self._repository.default_folder(workspace_id)
        if destination is None:
            raise UseCaseError(Failure.NOT_FOUND)
        folder, meeting_ids = await self._repository.restore(workspace_id, folder_id)
        for meeting_id in meeting_ids:
            await self._audit.write(
                MeetingMoved(
                    actor_id, workspace_id, meeting_id, now, destination.folder_id, folder_id
                )
            )
        return folder


class WorkspaceContent:
    """What a workspace holds, for Accounts (`IWorkspaceContent`); the Owner check is theirs."""

    def __init__(self, repository: IMeetingRepository) -> None:
        self._repository: IMeetingRepository = repository

    async def add_default_folder(self, workspace_id: UUID, now: datetime) -> None:
        await self._repository.save_folder(
            Folder(
                folder_id=uuid4(),
                workspace_id=workspace_id,
                name="General",
                created_at=now,
                is_default=True,
            )
        )

    async def remove_meetings(self, workspace_id: UUID, now: datetime) -> None:
        # One by one, so each recording is queued for deletion from storage.
        for meeting_id in await self._repository.workspace_meetings(workspace_id):
            await self._repository.remove(meeting_id, now)
