from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ..access_policy.repositories import AccessRepository
from ..access_policy.services import AccessCollaborators, AccessPolicy, AccessService
from ..accounts.enums import NotesTemplate
from ..accounts.repositories import MembershipRepository
from ..accounts.services import WorkspaceMembershipService
from ..audit.contracts import IContentAuditWriter
from ..audit.services import AuditWriter
from ..meetings.contracts import QueuedNotes
from ..meetings.persistence import MeetingPersistence, PersistenceDependencies
from ..meetings.recordings import RecordingObjects
from ..meetings.repositories import FolderRepository, MeetingRepository
from ..meetings.services import FolderService, MeetingService
from ..meetings.settings import MeetingSettings
from ..shared.database import Database, DatabaseSettings, IUseCaseTransactions
from ..shared.errors import Failure, UseCaseError
from ..shared.storage import connect_s3_storage
from .processing_port import IMeetingProcessing


class CompositionRoot:
    def __init__(self, database: Database | None = None) -> None:
        self._database: Database | None = database

    def database(self) -> Database:
        if self._database is None:
            try:
                self._database = Database(DatabaseSettings.model_validate({}))
            except ValidationError:
                raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE) from None
        return self._database

    async def transaction(self) -> AsyncGenerator[AsyncSession]:
        async with self.database().transaction() as session:
            yield session

    @asynccontextmanager
    async def lifespan(self, _app: FastAPI) -> AsyncGenerator[None]:
        try:
            yield
        finally:
            if self._database is not None:
                await self._database.close()


async def transaction() -> AsyncSession:
    raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE)


Session = Annotated[AsyncSession, Depends(transaction, scope="function")]


def content_audit(session: Session) -> IContentAuditWriter:
    return AuditWriter(session)


ContentAudit = Annotated[IContentAuditWriter, Depends(content_audit)]


def meeting_service(session: Session, audit: ContentAudit) -> MeetingService:
    return MeetingService(
        MeetingRepository(session),
        AccessPolicy(
            AccessRepository(session), WorkspaceMembershipService(MembershipRepository(session))
        ),
        audit,
    )


Meetings = Annotated[MeetingService, Depends(meeting_service)]


class UnavailableMeetingProcessing:
    async def queue_transcription(self, meeting_id: UUID) -> None:
        del meeting_id
        raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE)

    async def queue_notes(
        self,
        meeting_id: UUID,
        requester_id: UUID,
        preset: NotesTemplate | None,
        *,
        use_builtin_model: bool,
        now: datetime,
    ) -> QueuedNotes:
        del meeting_id, requester_id, preset, use_builtin_model, now
        raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE)


def meeting_processing() -> IMeetingProcessing:
    return UnavailableMeetingProcessing()


Processing = Annotated[IMeetingProcessing, Depends(meeting_processing)]


def meeting_persistence(
    session: Session, meetings: Meetings, audit: ContentAudit
) -> MeetingPersistence:
    settings = MeetingSettings()
    return MeetingPersistence(
        PersistenceDependencies(
            meetings,
            MeetingRepository(session),
            WorkspaceMembershipService(MembershipRepository(session)),
            audit,
        ),
        hosted_limit=1000 if settings.meetings_hosted else None,
    )


Persistence = Annotated[MeetingPersistence, Depends(meeting_persistence)]


def recording_objects() -> RecordingObjects:
    settings = MeetingSettings()
    if settings.storage is None:
        raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE)
    return RecordingObjects(connect_s3_storage(settings.storage))


Recordings = Annotated[RecordingObjects, Depends(recording_objects)]


def runtime_database() -> IUseCaseTransactions:
    raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE)


class UploadProtection:
    def __init__(self, database: IUseCaseTransactions, repository: MeetingRepository) -> None:
        self._database: IUseCaseTransactions = database
        self._repository: MeetingRepository = repository

    async def reserve(self, key: str) -> None:
        async with self._database.transaction() as session:
            await MeetingRepository(session).reserve_upload(key)
        await self._repository.lock_upload(key)

    async def release(self, key: str) -> None:
        await self._repository.release_upload(key)


def upload_protection(
    session: Session,
    database: Annotated[IUseCaseTransactions, Depends(runtime_database)],
) -> UploadProtection:
    return UploadProtection(database, MeetingRepository(session))


UploadGuard = Annotated[UploadProtection, Depends(upload_protection)]


class UnavailableShareNotifications:
    async def enqueue(self, share_id: UUID, creator_id: UUID, requester_id: UUID) -> None:
        del share_id, creator_id, requester_id
        raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE)


def access_service(session: Session, audit: ContentAudit) -> AccessService:
    return AccessService(
        AccessCollaborators(
            AccessRepository(session),
            MeetingRepository(session),
            WorkspaceMembershipService(MembershipRepository(session)),
            audit,
            UnavailableShareNotifications(),
        )
    )


Access = Annotated[AccessService, Depends(access_service)]


def folder_service(session: Session) -> FolderService:
    return FolderService(
        FolderRepository(session),
        WorkspaceMembershipService(MembershipRepository(session)),
        AuditWriter(session),
    )


Folders = Annotated[FolderService, Depends(folder_service)]
