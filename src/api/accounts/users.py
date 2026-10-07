import hashlib
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from .models import User, Workspace, WorkspaceMembership
from .schemas import Preset, Role


async def create_user(db: AsyncSession, email: str, name: str, password: str) -> User:
    """Adds an account with its personal workspace; the caller commits.

    Registration will call this once it exists; until then only tests do.
    """
    now = datetime.now(UTC)
    user = User(
        email=email.lower(),
        name=name,
        # The lowercased email is the salt, so equal passwords still hash differently per user.
        password_hash=hashlib.sha256((email.lower() + password).encode()).hexdigest(),
        terms_accepted_at=now,
        created_at=now,
    )
    personal = Workspace(name=name, default_preset=Preset.SUMMARY, is_personal=True, created_at=now)
    db.add_all([user, personal])
    await db.flush()
    db.add(
        WorkspaceMembership(
            workspace_id=personal.workspace_id, user_id=user.user_id, role=Role.OWNER, joined_at=now
        )
    )
    return user
