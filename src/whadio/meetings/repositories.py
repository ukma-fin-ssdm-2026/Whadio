from datetime import datetime
from typing import Protocol
from uuid import UUID

from psycopg.errors import UniqueViolation
from sqlalchemy import Select, case, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..access_policy.contracts import MeetingScope
from ..shared.errors import Failure, UseCaseError
from ..shared.pagination import ListWindow
from .contracts import ContextReference, MeetingFilter, NoteVersion, TranscriptVersion
from .enums import AccessMode, ProcessingState
from .models import (
    Folder,
    FolderRecovery,
    FolderRecoveryMeeting,
    GlossaryTerm,
    Meeting,
    Note,
    NoteContextMeeting,
    RecordingDeletion,
    Speaker,
    Transcript,
    TranscriptRevision,
    TranscriptSegment,
)


class IMeetingRepository(Protocol):
    async def capacity_overflow(self, workspace_ids: list[UUID], limit: int) -> list[Meeting]: ...

    async def save_notes(self, note: Note, context: tuple[ContextReference, ...]) -> None: ...

    async def reserve_upload(self, key: str) -> None: ...

    async def lock_upload(self, key: str) -> None: ...

    async def release_upload(self, key: str) -> None: ...

    async def save_initial(self, version: TranscriptVersion) -> None: ...

    async def folder_counts(
        self, workspace_id: UUID, folder_ids: list[UUID], grants: Select[UUID]
    ) -> dict[UUID, int]: ...

    async def remove(self, meeting_id: UUID, now: datetime) -> None: ...

    async def visible(self, filters: MeetingFilter, grants: Select[UUID]) -> list[Meeting]: ...

    async def scope(self, meeting_id: UUID, *, lock: bool = False) -> MeetingScope: ...

    async def get(self, meeting_id: UUID, *, lock: bool = False) -> Meeting: ...

    async def folders(self, workspace_id: UUID, page: ListWindow | None = None) -> list[Folder]: ...

    async def folder(
        self, workspace_id: UUID, folder_id: UUID, *, lock: bool = False
    ) -> Folder: ...

    async def folder_name_exists(self, workspace_id: UUID, name: str, exclude: UUID) -> bool: ...

    async def save_folder(self, folder: Folder) -> None: ...

    async def save(self, meeting: Meeting) -> None: ...

    async def version(
        self, meeting_id: UUID, revision_id: UUID | None = None
    ) -> TranscriptVersion: ...

    async def revisions(
        self, meeting_id: UUID, page: ListWindow | None = None
    ) -> list[TranscriptRevision]: ...

    async def save_version(self, version: TranscriptVersion) -> None: ...

    async def notes(
        self, meeting_id: UUID, page: ListWindow | None = None
    ) -> list[NoteVersion]: ...

    async def glossary(
        self, workspace_id: UUID, page: ListWindow | None = None
    ) -> list[GlossaryTerm]: ...

    async def term(self, workspace_id: UUID, term_id: UUID) -> GlossaryTerm: ...

    async def save_term(self, term: GlossaryTerm) -> None: ...

    async def remove_term(self, term_id: UUID) -> None: ...

    async def processed_in_folder(self, folder_id: UUID, limit: int) -> list[Meeting]: ...

    async def workspace_meetings(self, workspace_id: UUID) -> list[UUID]: ...


class MeetingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def reserve_upload(self, key: str) -> None:
        self._session.add(RecordingDeletion(storage_key=key))
        await self._session.flush()

    async def lock_upload(self, key: str) -> None:
        found = await self._session.scalar(
            select(RecordingDeletion.deletion_id)
            .where(RecordingDeletion.storage_key == key)
            .with_for_update()
        )
        if found is None:
            raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE)

    async def release_upload(self, key: str) -> None:
        await self._session.execute(
            delete(RecordingDeletion).where(RecordingDeletion.storage_key == key)
        )

    async def capacity_overflow(self, workspace_ids: list[UUID], limit: int) -> list[Meeting]:
        count = await self._session.scalar(
            select(func.count(Meeting.meeting_id))
            .join(Folder)
            .where(
                Folder.workspace_id.in_(workspace_ids),
                Meeting.processing_state != ProcessingState.RECORDING,
            )
        )
        overflow = max(0, (count or 0) - limit + 1)
        if not overflow:
            return []
        return list(
            await self._session.scalars(
                select(Meeting)
                .join(Folder)
                .where(
                    Folder.workspace_id.in_(workspace_ids),
                    Meeting.processing_state != ProcessingState.RECORDING,
                )
                .order_by(Meeting.created_at, Meeting.meeting_id)
                .limit(overflow)
                .with_for_update(of=Meeting)
            )
        )

    async def save_notes(self, note: Note, context: tuple[ContextReference, ...]) -> None:
        self._session.add(note)
        await self._session.flush()
        existing = set(
            await self._session.scalars(
                select(Meeting.meeting_id).where(
                    Meeting.meeting_id.in_(item.meeting_id for item in context)
                )
            )
        )
        self._session.add_all(
            NoteContextMeeting(
                note_id=note.note_id,
                context_meeting_id=item.meeting_id if item.meeting_id in existing else None,
                context_meeting_name_snapshot=item.name,
            )
            for item in context
        )
        await self._session.flush()

    async def remove(self, meeting_id: UUID, now: datetime) -> None:
        meeting = await self.get(meeting_id, lock=True)
        if meeting.storage_path is not None and meeting.recording_deleted_at is None:
            self._session.add(RecordingDeletion(storage_key=meeting.storage_path, created_at=now))
            await self._session.flush()
        await self._session.execute(delete(Meeting).where(Meeting.meeting_id == meeting_id))

    async def visible(self, filters: MeetingFilter, grants: Select[UUID]) -> list[Meeting]:
        statement = (
            select(Meeting)
            .join(Folder)
            .where(
                Folder.workspace_id == filters.workspace_id,
                or_(Meeting.access_mode == "workspace", Meeting.meeting_id.in_(grants)),
            )
        )
        if filters.folder_id is not None:
            statement = statement.where(Meeting.folder_id == filters.folder_id)
        if filters.name is not None:
            statement = statement.where(Meeting.name.icontains(filters.name, autoescape=True))
        if filters.recorded_from is not None:
            statement = statement.where(Meeting.recorded_at >= filters.recorded_from)
        if filters.recorded_to is not None:
            statement = statement.where(Meeting.recorded_at < filters.recorded_to)
        if filters.after is not None:
            recorded_at, meeting_id = filters.after
            statement = statement.where(
                or_(
                    Meeting.recorded_at < recorded_at,
                    (Meeting.recorded_at == recorded_at) & (Meeting.meeting_id < meeting_id),
                )
            )
        if filters.limit is not None:
            statement = statement.limit(filters.limit)
        return list(
            await self._session.scalars(
                statement.order_by(Meeting.recorded_at.desc(), Meeting.meeting_id.desc())
            )
        )

    async def scope(self, meeting_id: UUID, *, lock: bool = False) -> MeetingScope:
        meeting = await self.get(meeting_id, lock=lock)
        folder = await self._session.get(Folder, meeting.folder_id)
        if folder is None:
            raise UseCaseError(Failure.NOT_FOUND)
        return MeetingScope(
            meeting_id,
            folder.workspace_id,
            meeting.created_by_user_id,
            meeting.access_mode == "restricted",
        )

    async def set_restricted(self, meeting_id: UUID, *, restricted: bool) -> None:
        meeting = await self.get(meeting_id)
        meeting.access_mode = AccessMode.RESTRICTED if restricted else AccessMode.WORKSPACE
        await self.save(meeting)

    async def get(self, meeting_id: UUID, *, lock: bool = False) -> Meeting:
        statement = select(Meeting).where(Meeting.meeting_id == meeting_id)
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        meeting = await self._session.scalar(statement)
        if meeting is None:
            raise UseCaseError(Failure.NOT_FOUND)
        return meeting

    async def folders(self, workspace_id: UUID, page: ListWindow | None = None) -> list[Folder]:
        key = case((Folder.is_default, "0:"), else_="1:") + func.lower(Folder.name)
        statement = select(Folder).where(Folder.workspace_id == workspace_id)
        if page is not None:
            if page.after is not None:
                statement = statement.where(
                    (key > page.after.key)
                    | ((key == page.after.key) & (Folder.folder_id > page.after.item_id))
                )
            statement = statement.limit(page.limit)
        return list(await self._session.scalars(statement.order_by(key, Folder.folder_id)))

    async def folder_counts(
        self, workspace_id: UUID, folder_ids: list[UUID], grants: Select[UUID]
    ) -> dict[UUID, int]:
        rows = await self._session.execute(
            select(Meeting.folder_id, func.count(Meeting.meeting_id))
            .join(Folder)
            .where(
                Folder.workspace_id == workspace_id,
                Meeting.folder_id.in_(folder_ids),
                (Meeting.access_mode == AccessMode.WORKSPACE) | Meeting.meeting_id.in_(grants),
            )
            .group_by(Meeting.folder_id)
        )
        return dict(rows.all())

    async def folder(self, workspace_id: UUID, folder_id: UUID, *, lock: bool = False) -> Folder:
        statement = select(Folder).where(
            Folder.workspace_id == workspace_id, Folder.folder_id == folder_id
        )
        if lock:
            statement = statement.with_for_update()
        folder = await self._session.scalar(statement)
        if folder is None:
            raise UseCaseError(Failure.NOT_FOUND)
        return folder

    async def folder_name_exists(self, workspace_id: UUID, name: str, exclude: UUID) -> bool:
        return (
            await self._session.scalar(
                select(Folder.folder_id).where(
                    Folder.workspace_id == workspace_id,
                    func.lower(Folder.name) == name.lower(),
                    Folder.folder_id != exclude,
                )
            )
            is not None
        )

    async def save_folder(self, folder: Folder) -> None:
        self._session.add(folder)
        try:
            await self._session.flush()
        except IntegrityError as error:
            if (
                isinstance(error.orig, UniqueViolation)
                and error.orig.diag.constraint_name == "uq_folder_workspace_name"
            ):
                raise UseCaseError(Failure.FOLDER_EXISTS) from None
            raise

    async def save(self, meeting: Meeting) -> None:
        self._session.add(meeting)
        await self._session.flush()

    async def version(self, meeting_id: UUID, revision_id: UUID | None = None) -> TranscriptVersion:
        transcript = await self._session.scalar(
            select(Transcript).where(Transcript.meeting_id == meeting_id)
        )
        if transcript is None:
            raise UseCaseError(Failure.NOT_TRANSCRIBED)
        revision = await self._session.scalar(
            select(TranscriptRevision).where(
                TranscriptRevision.transcript_id == transcript.transcript_id,
                TranscriptRevision.revision_id == (revision_id or transcript.current_revision_id),
            )
        )
        if revision is None:
            raise UseCaseError(Failure.NOT_FOUND)
        original = await self._session.scalar(
            select(TranscriptRevision.revision_id).where(
                TranscriptRevision.transcript_id == transcript.transcript_id,
                TranscriptRevision.revision_type == "original",
            )
        )
        if original is None:
            raise UseCaseError(Failure.NOT_TRANSCRIBED)
        speakers = list(
            await self._session.scalars(
                select(Speaker)
                .where(Speaker.revision_id == revision.revision_id)
                .order_by(Speaker.speaker_id)
            )
        )
        segments = list(
            await self._session.scalars(
                select(TranscriptSegment)
                .where(TranscriptSegment.revision_id == revision.revision_id)
                .order_by(TranscriptSegment.start_time_seconds, TranscriptSegment.segment_id)
            )
        )
        return TranscriptVersion(
            transcript,
            revision,
            original,
            transcript.current_revision_id != original,
            speakers,
            segments,
        )

    async def revisions(
        self, meeting_id: UUID, page: ListWindow | None = None
    ) -> list[TranscriptRevision]:
        statement = (
            select(TranscriptRevision)
            .join(Transcript, Transcript.transcript_id == TranscriptRevision.transcript_id)
            .where(Transcript.meeting_id == meeting_id)
        )
        if page is not None:
            if page.after is not None:
                timestamp = datetime.fromisoformat(page.after.key)
                statement = statement.where(
                    (TranscriptRevision.created_at < timestamp)
                    | (
                        (TranscriptRevision.created_at == timestamp)
                        & (TranscriptRevision.revision_id < page.after.item_id)
                    )
                )
            statement = statement.limit(page.limit)
        return list(
            await self._session.scalars(
                statement.order_by(
                    TranscriptRevision.created_at.desc(), TranscriptRevision.revision_id.desc()
                )
            )
        )

    async def save_initial(self, version: TranscriptVersion) -> None:
        self._session.add(version.transcript)
        await self._session.flush()
        await self.save_version(version)

    async def save_version(self, version: TranscriptVersion) -> None:
        self._session.add(version.revision)
        await self._session.flush()
        self._session.add_all(version.speakers)
        await self._session.flush()
        self._session.add_all(version.segments)
        version.transcript.current_revision_id = version.revision.revision_id
        await self._session.flush()

    async def notes(self, meeting_id: UUID, page: ListWindow | None = None) -> list[NoteVersion]:
        statement = select(Note).where(Note.meeting_id == meeting_id)
        if page is not None:
            if page.after is not None:
                timestamp = datetime.fromisoformat(page.after.key)
                statement = statement.where(
                    (Note.created_at < timestamp)
                    | ((Note.created_at == timestamp) & (Note.note_id < page.after.item_id))
                )
            statement = statement.limit(page.limit)
        notes = list(
            await self._session.scalars(
                statement.order_by(Note.created_at.desc(), Note.note_id.desc())
            )
        )
        if not notes:
            return []
        current = await self._session.scalar(
            select(Note.note_id)
            .where(Note.meeting_id == meeting_id)
            .order_by(Note.created_at.desc(), Note.note_id.desc())
            .limit(1)
        )
        context = list(
            await self._session.scalars(
                select(NoteContextMeeting)
                .where(NoteContextMeeting.note_id.in_(n.note_id for n in notes))
                .order_by(NoteContextMeeting.note_context_meeting_id)
            )
        )
        return [
            NoteVersion(
                note, [c for c in context if c.note_id == note.note_id], note.note_id == current
            )
            for note in notes
        ]

    async def glossary(
        self, workspace_id: UUID, page: ListWindow | None = None
    ) -> list[GlossaryTerm]:
        key = func.lower(GlossaryTerm.term)
        statement = select(GlossaryTerm).where(GlossaryTerm.workspace_id == workspace_id)
        if page is not None:
            if page.after is not None:
                statement = statement.where(
                    (key > page.after.key)
                    | ((key == page.after.key) & (GlossaryTerm.term_id > page.after.item_id))
                )
            statement = statement.limit(page.limit)
        return list(await self._session.scalars(statement.order_by(key, GlossaryTerm.term_id)))

    async def term(self, workspace_id: UUID, term_id: UUID) -> GlossaryTerm:
        term = await self._session.scalar(
            select(GlossaryTerm).where(
                GlossaryTerm.workspace_id == workspace_id, GlossaryTerm.term_id == term_id
            )
        )
        if term is None:
            raise UseCaseError(Failure.NOT_FOUND)
        return term

    async def save_term(self, term: GlossaryTerm) -> None:
        self._session.add(term)
        try:
            await self._session.flush()
        except IntegrityError as error:
            if (
                isinstance(error.orig, UniqueViolation)
                and error.orig.diag.constraint_name == "uq_glossary_workspace_term"
            ):
                raise UseCaseError(Failure.TERM_EXISTS) from None
            raise

    async def remove_term(self, term_id: UUID) -> None:
        await self._session.execute(delete(GlossaryTerm).where(GlossaryTerm.term_id == term_id))

    async def processed_in_folder(self, folder_id: UUID, limit: int) -> list[Meeting]:
        return list(
            await self._session.scalars(
                select(Meeting)
                .where(
                    Meeting.folder_id == folder_id,
                    Meeting.access_mode == AccessMode.WORKSPACE,
                    Meeting.processing_state == ProcessingState.PROCESSED,
                )
                .order_by(Meeting.recorded_at.desc(), Meeting.meeting_id.desc())
                .limit(limit)
            )
        )

    async def workspace_meetings(self, workspace_id: UUID) -> list[UUID]:
        return list(
            await self._session.scalars(
                select(Meeting.meeting_id).join(Folder).where(Folder.workspace_id == workspace_id)
            )
        )


class IFolderRepository(Protocol):
    async def folder(self, workspace_id: UUID, folder_id: UUID) -> Folder | None: ...

    async def default_folder(self, workspace_id: UUID) -> Folder | None: ...

    async def move_meetings(self, folder_id: UUID, destination_id: UUID) -> list[UUID]: ...

    async def remember(self, folder: Folder, meeting_ids: list[UUID], now: datetime) -> None: ...

    async def restore(self, workspace_id: UUID, folder_id: UUID) -> tuple[Folder, list[UUID]]: ...

    async def remove_folder(self, folder_id: UUID) -> None: ...


class FolderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def folder(self, workspace_id: UUID, folder_id: UUID) -> Folder | None:
        return await self._session.scalar(
            select(Folder)
            .where(Folder.workspace_id == workspace_id, Folder.folder_id == folder_id)
            .with_for_update()
        )

    async def default_folder(self, workspace_id: UUID) -> Folder | None:
        return await self._session.scalar(
            select(Folder)
            .where(Folder.workspace_id == workspace_id, Folder.is_default)
            .with_for_update()
        )

    async def move_meetings(self, folder_id: UUID, destination_id: UUID) -> list[UUID]:
        return list(
            await self._session.scalars(
                update(Meeting)
                .where(Meeting.folder_id == folder_id)
                .values(folder_id=destination_id)
                .returning(Meeting.meeting_id)
            )
        )

    async def remember(self, folder: Folder, meeting_ids: list[UUID], now: datetime) -> None:
        self._session.add(
            FolderRecovery(
                folder_id=folder.folder_id,
                workspace_id=folder.workspace_id,
                name=folder.name,
                created_at=folder.created_at,
                deleted_at=now,
            )
        )
        await self._session.flush()
        self._session.add_all(
            FolderRecoveryMeeting(folder_id=folder.folder_id, meeting_id=mid) for mid in meeting_ids
        )
        await self._session.flush()

    async def restore(self, workspace_id: UUID, folder_id: UUID) -> tuple[Folder, list[UUID]]:
        recovery = await self._session.scalar(
            select(FolderRecovery)
            .where(
                FolderRecovery.workspace_id == workspace_id, FolderRecovery.folder_id == folder_id
            )
            .with_for_update()
        )
        if recovery is None:
            raise UseCaseError(Failure.NOT_FOUND)
        destination = await self.default_folder(workspace_id)
        if destination is None:
            raise UseCaseError(Failure.NOT_FOUND)
        rows = list(
            await self._session.scalars(
                select(Meeting)
                .join(FolderRecoveryMeeting, FolderRecoveryMeeting.meeting_id == Meeting.meeting_id)
                .where(FolderRecoveryMeeting.folder_id == folder_id)
                .order_by(Meeting.meeting_id)
                .with_for_update(of=Meeting)
            )
        )
        if any(row.folder_id != destination.folder_id for row in rows):
            raise UseCaseError(Failure.FOLDER_RECOVERY_CONFLICT)
        folder = Folder(
            folder_id=folder_id,
            workspace_id=workspace_id,
            name=recovery.name,
            created_at=recovery.created_at,
            is_default=False,
        )
        await MeetingRepository(self._session).save_folder(folder)
        for row in rows:
            row.folder_id = folder_id
        await self._session.flush()
        await self._session.execute(
            delete(FolderRecovery).where(FolderRecovery.folder_id == folder_id)
        )
        return folder, [row.meeting_id for row in rows]

    async def remove_folder(self, folder_id: UUID) -> None:
        await self._session.execute(delete(Folder).where(Folder.folder_id == folder_id))
