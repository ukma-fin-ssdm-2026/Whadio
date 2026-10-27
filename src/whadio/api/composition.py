import asyncio
import logging
from collections.abc import AsyncGenerator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import Depends, FastAPI
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ..access_policy.contracts import IMeetingAccessSource
from ..access_policy.repositories import AccessRepository
from ..access_policy.services import (
    AccessCollaborators,
    AccessPolicy,
    AccessService,
    IShareRequestNotifier,
)
from ..accounts.administrators import AdministratorRepository, AdministratorService
from ..accounts.contracts import UserProfile
from ..accounts.enums import NotesTemplate
from ..accounts.passwords import Argon2PasswordHasher
from ..accounts.repositories import (
    McpKeyRepository,
    MembershipRepository,
    SessionRepository,
    WorkspaceRepository,
    WorkspaceSettingsRepository,
)
from ..accounts.services import (
    McpKeyService,
    SignInService,
    WorkspaceMembershipService,
    WorkspaceService,
    WorkspaceSettingsService,
)
from ..admin.services import AdminService
from ..audit.contracts import IContentAuditWriter
from ..audit.services import AuditWriter
from ..capture.repositories import CaptureRepository
from ..capture.services import (
    CaptureCollaborators,
    CaptureService,
    CaptureSpeakerTimeline,
    IChunkStorage,
)
from ..export.services import ExportService
from ..meetings.contracts import EvictionNotice, IEvictionNotifier, QueuedNotes
from ..meetings.monitoring import MeetingMetadata
from ..meetings.persistence import MeetingPersistence, PersistenceDependencies
from ..meetings.processing import IMeetingProcessing
from ..meetings.recordings import RecordingObjects
from ..meetings.repositories import FolderRepository, MeetingRepository
from ..meetings.services import FolderService, MeetingService, WorkspaceContent
from ..meetings.settings import MeetingSettings
from ..notifications.repositories import INotificationOutbox, NotificationOutboxRepository
from ..notifications.templates import (
    HostedEviction,
    NoticeKind,
    ProcessingFailed,
    ProcessingFinished,
    ShareAccessRequest,
)
from ..processing.consumer import (
    ProcessingTransactions,
    ResultSource,
    WorkerUsers,
    job_publisher,
    serve_publishing,
    serve_results,
)
from ..processing.enums import ProcessingOutcome
from ..processing.monitoring import IJobMonitoring, JobMonitoring
from ..processing.repositories import JobRepository
from ..processing.services import ProcessingCollaborators, ProcessingNotice, ProcessingService
from ..shared.database import Database, DatabaseSettings, IUseCaseTransactions
from ..shared.errors import Failure, UseCaseError
from ..shared.settings import PublicUrlSettings
from ..shared.storage import IObjectStorage, connect_s3_storage
from .settings import WebSettings

logger = logging.getLogger(__name__)


class CompositionRoot:
    def __init__(
        self, database: Database | None = None, *, public_settings: PublicUrlSettings | None = None
    ) -> None:
        settings = (
            public_settings if public_settings is not None else PublicUrlSettings.model_validate({})
        )
        self.public_url: str = str(settings.public_url or "http://localhost:3000")
        self.api_public_url: str = str(settings.api_public_url or self.public_url)
        self._database: Database | None = database
        self._storage: IObjectStorage | None = None
        # Present while jobs are being published; setting it publishes the ones just committed.
        self._queued: asyncio.Event | None = None

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
        # Reached only after the commit, which may have queued a job.
        if self._queued is not None:
            self._queued.set()

    def processing(self, session: AsyncSession) -> IMeetingProcessing:
        if self._queued is None:
            return UnavailableMeetingProcessing()
        return self._processing_service(session)

    def _processing_service(self, session: AsyncSession) -> ProcessingService:
        if self._storage is None:
            raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE)
        return processing_service(session, self._storage)

    @asynccontextmanager
    async def lifespan(self, _app: FastAPI) -> AsyncGenerator[None]:
        settings, storage = WebSettings(), MeetingSettings().storage
        stop = asyncio.Event()
        tasks: list[asyncio.Task[None]] = []
        try:
            async with AsyncExitStack() as stack:
                if settings.broker is not None and storage is not None:
                    self._storage = connect_s3_storage(storage)
                    queued = asyncio.Event()
                    transactions = ProcessingTransactions(
                        self.database(),
                        self._processing_service,
                        await stack.enter_async_context(job_publisher(settings.broker)),
                        queued,
                    )
                    tasks = [
                        asyncio.create_task(serve_publishing(transactions, queued, stop)),
                        asyncio.create_task(
                            serve_results(
                                settings.broker,
                                transactions,
                                ResultSource(
                                    WorkerUsers(
                                        transcription=settings.asr_broker_user
                                        or settings.broker.user
                                        or "",
                                        notes=settings.notes_broker_user
                                        or settings.broker.user
                                        or "",
                                    )
                                ),
                                stop,
                            )
                        ),
                    ]
                    for task in tasks:
                        task.add_done_callback(_log_failure)
                    self._queued = queued
                try:
                    yield
                finally:
                    stop.set()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    self._queued = None
        finally:
            if self._database is not None:
                await self._database.close()


def _log_failure(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.error("A processing task stopped", exc_info=task.exception())


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


def meeting_processing(session: Session) -> IMeetingProcessing:
    del session
    return UnavailableMeetingProcessing()


Processing = Annotated[IMeetingProcessing, Depends(meeting_processing)]


class OutboxEvictionNotices:
    """Meetings' `IEvictionNotifier`, answered by the notification outbox."""

    def __init__(self, outbox: INotificationOutbox) -> None:
        self._outbox: INotificationOutbox = outbox

    async def enqueue(self, notice: EvictionNotice) -> None:
        await self._outbox.reserve(
            notice.recipient_id,
            f"{NoticeKind.HOSTED_EVICTION}:{notice.meeting_id}:{notice.recipient_id}",
            HostedEviction(meeting_name=notice.meeting_name),
        )


class OutboxProcessingNotices:
    """Processing's `IProcessingNotifier`, answered by the notification outbox."""

    def __init__(self, outbox: INotificationOutbox) -> None:
        self._outbox: INotificationOutbox = outbox

    async def notify(self, notice: ProcessingNotice) -> None:
        match notice.outcome:
            case ProcessingOutcome.FINISHED:
                model = ProcessingFinished(
                    meeting_id=notice.meeting_id, meeting_name=notice.meeting_name
                )
            case ProcessingOutcome.FAILED:
                model = ProcessingFailed(
                    meeting_id=notice.meeting_id, meeting_name=notice.meeting_name
                )
        await self._outbox.reserve(
            notice.recipient_id, f"{model.kind}:{notice.meeting_id}:{notice.recipient_id}", model
        )


class PolicyMeetingReaders:
    """Processing's `IMeetingReaders`, answered by Access Policy."""

    def __init__(self, meetings: IMeetingAccessSource, policy: AccessPolicy) -> None:
        self._meetings: IMeetingAccessSource = meetings
        self._policy: AccessPolicy = policy

    async def can_read(self, user_id: UUID, meeting_id: UUID) -> bool:
        try:
            await self._policy.authorize(await self._meetings.scope(meeting_id), user_id)
        except UseCaseError as error:
            if error.code == Failure.NOT_FOUND:
                return False
            raise
        return True


def eviction_notifications(session: Session) -> IEvictionNotifier:
    return OutboxEvictionNotices(NotificationOutboxRepository(session))


def processing_service(session: AsyncSession, storage: IObjectStorage) -> ProcessingService:
    meetings = meeting_service(session, AuditWriter(session))
    memberships = WorkspaceMembershipService(MembershipRepository(session))
    return ProcessingService(
        ProcessingCollaborators(
            JobRepository(session),
            meetings,
            MeetingPersistence(
                PersistenceDependencies(
                    meetings,
                    MeetingRepository(session),
                    memberships,
                    AuditWriter(session),
                    AccessPolicy(AccessRepository(session), memberships),
                    OutboxEvictionNotices(NotificationOutboxRepository(session)),
                )
            ),
            WorkspaceSettingsService(WorkspaceSettingsRepository(session)),
            storage,
            CaptureSpeakerTimeline(CaptureRepository(session)),
            OutboxProcessingNotices(NotificationOutboxRepository(session)),
            PolicyMeetingReaders(
                MeetingRepository(session), AccessPolicy(AccessRepository(session), memberships)
            ),
        )
    )


def meeting_persistence(
    session: Session,
    meetings: Meetings,
    audit: ContentAudit,
    notifications: Annotated[IEvictionNotifier, Depends(eviction_notifications)],
) -> MeetingPersistence:
    settings = MeetingSettings()
    return MeetingPersistence(
        PersistenceDependencies(
            meetings,
            MeetingRepository(session),
            WorkspaceMembershipService(MembershipRepository(session)),
            audit,
            AccessPolicy(
                AccessRepository(session), WorkspaceMembershipService(MembershipRepository(session))
            ),
            notifications,
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


class IProfiles(Protocol):
    async def profile(self, user_id: UUID, /) -> UserProfile | None: ...


class OutboxShareNotices:
    """Access Policy's `IShareRequestNotifier`, answered by the notification outbox."""

    def __init__(self, outbox: INotificationOutbox, profiles: IProfiles) -> None:
        self._outbox: INotificationOutbox = outbox
        self._profiles: IProfiles = profiles

    async def enqueue(self, share_id: UUID, creator_id: UUID, requester_id: UUID) -> None:
        requester = await self._profiles.profile(requester_id)
        if requester is None:
            raise UseCaseError(Failure.NOT_FOUND)
        await self._outbox.reserve(
            creator_id,
            f"{NoticeKind.SHARE_ACCESS_REQUEST}:{share_id}:{requester_id}",
            ShareAccessRequest(
                share_id=share_id, requester_name=requester.name, requester_email=requester.email
            ),
        )


def share_notifications(session: Session) -> IShareRequestNotifier:
    return OutboxShareNotices(
        NotificationOutboxRepository(session),
        WorkspaceMembershipService(MembershipRepository(session)),
    )


def access_service(
    session: Session,
    audit: ContentAudit,
    notifications: Annotated[IShareRequestNotifier, Depends(share_notifications)],
) -> AccessService:
    return AccessService(
        AccessCollaborators(
            AccessRepository(session),
            MeetingRepository(session),
            WorkspaceMembershipService(MembershipRepository(session)),
            audit,
            notifications,
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


def sign_in_service(session: Session) -> SignInService:
    return SignInService(SessionRepository(session), Argon2PasswordHasher())


SignIns = Annotated[SignInService, Depends(sign_in_service)]


def mcp_key_service(session: Session) -> McpKeyService:
    return McpKeyService(McpKeyRepository(session), AuditWriter(session))


McpKeys = Annotated[McpKeyService, Depends(mcp_key_service)]


def workspace_service(session: Session) -> WorkspaceService:
    return WorkspaceService(
        WorkspaceRepository(session),
        WorkspaceMembershipService(MembershipRepository(session)),
        WorkspaceContent(MeetingRepository(session)),
        AuditWriter(session),
    )


Workspaces = Annotated[WorkspaceService, Depends(workspace_service)]


def capture_storage() -> IChunkStorage:
    settings = MeetingSettings()
    if settings.storage is None:
        raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE)
    return connect_s3_storage(settings.storage)


def capture_service(
    session: Session,
    storage: Annotated[IChunkStorage, Depends(capture_storage)],
    workspaces: Workspaces,
    meetings: Meetings,
    persistence: Persistence,
    processing: Processing,
) -> CaptureService:
    return CaptureService(
        CaptureCollaborators(
            CaptureRepository(session),
            storage,
            workspaces,
            meetings,
            persistence,
            meetings,
            persistence,
            processing,
        )
    )


Captures = Annotated[CaptureService, Depends(capture_service)]


@dataclass(frozen=True)
class RuntimeIntegrations:
    processing: Callable[[AsyncSession], IMeetingProcessing] | None = None


def connect_integrations(app: FastAPI, integrations: RuntimeIntegrations) -> None:
    def processing(session: Session) -> IMeetingProcessing:
        factory = integrations.processing
        return UnavailableMeetingProcessing() if factory is None else factory(session)

    app.dependency_overrides[meeting_processing] = processing


def export_public_url() -> str:
    raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE)


def export_api_public_url() -> str:
    raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE)


def export_service(
    meetings: Meetings,
    public_url: Annotated[str, Depends(export_public_url)],
    api_public_url: Annotated[str, Depends(export_api_public_url)],
) -> ExportService:
    return ExportService(meetings, public_url, api_public_url)


Exports = Annotated[ExportService, Depends(export_service)]


def administrator_service(session: Session) -> AdministratorService:
    return AdministratorService(AdministratorRepository(session))


Administrators = Annotated[AdministratorService, Depends(administrator_service)]


def job_monitoring(session: Session) -> IJobMonitoring:
    return JobMonitoring(session, MeetingMetadata(session))


MonitoredJobs = Annotated[IJobMonitoring, Depends(job_monitoring)]


def admin_service(jobs: MonitoredJobs) -> AdminService:
    return AdminService(jobs)


Administration = Annotated[AdminService, Depends(admin_service)]
