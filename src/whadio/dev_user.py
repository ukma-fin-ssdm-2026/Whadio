import asyncio
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .accounts.enums import NotesTemplate, WorkspaceRole
from .accounts.models import Session, User, Workspace, WorkspaceMembership
from .accounts.passwords import Argon2PasswordHasher
from .meetings.models import Folder


async def ensure_dev_user(session: AsyncSession, *, email: str, name: str, password: str) -> bool:
    """Create a local account and workspace, or reset its credentials safely."""
    user = await session.scalar(select(User).where(func.lower(User.email) == email.lower()))
    password_hash = await asyncio.to_thread(Argon2PasswordHasher().hash, password)
    created = user is None

    if user is None:
        user = User(
            email=email,
            name=name,
            password_hash=password_hash,
            terms_accepted_at=datetime.now(UTC),
        )
        session.add(user)
        await session.flush()
    else:
        user.name = name
        user.password_hash = password_hash
        await session.execute(delete(Session).where(Session.user_id == user.user_id))

    personal = await session.scalar(
        select(Workspace)
        .join(
            WorkspaceMembership,
            WorkspaceMembership.workspace_id == Workspace.workspace_id,
        )
        .where(
            WorkspaceMembership.user_id == user.user_id,
            Workspace.is_personal.is_(True),
        )
    )
    if personal is None:
        personal = Workspace(
            name=name,
            default_template=NotesTemplate.DETAILED,
            is_personal=True,
        )
        session.add(personal)
        await session.flush()
        session.add(
            WorkspaceMembership(
                workspace_id=personal.workspace_id,
                user_id=user.user_id,
                role=WorkspaceRole.OWNER,
            )
        )
        session.add(
            Folder(
                workspace_id=personal.workspace_id,
                name="default",
                is_default=True,
            )
        )
        await session.flush()

    return created
