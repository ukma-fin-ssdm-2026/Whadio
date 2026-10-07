import hashlib
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.errors import not_found
from .models import User, Workspace, WorkspaceMembership
from .schemas import Preset, Provider, Role, UserRead, WorkspaceRead

DEMO_EMAIL: Final = "alice@whadio.dev"
DEMO_PASSWORD: Final = "whadio-demo-pass"

TEAM_WORKSPACE_ID: Final = UUID("7b1e9c40-2d3f-4a5b-8c6d-0e1f2a3b4c5d")
PERSONAL_WORKSPACE_ID: Final = UUID("1c2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5f")

ALICE: Final = UserRead(
    id=UUID("3f6c1d2e-8a4b-4c5d-9e0f-1a2b3c4d5e6f"),
    email=DEMO_EMAIL,
    name="Alice Owner",
    is_administrator=False,
    created_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
)

WORKSPACES: Final = {
    workspace.id: workspace
    for workspace in (
        WorkspaceRead(
            id=PERSONAL_WORKSPACE_ID,
            name="Alice Owner",
            is_personal=True,
            my_role=Role.OWNER,
            member_count=1,
            notes_provider=Provider.WHADIO,
            created_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
            default_preset=Preset.SUMMARY,
        ),
        WorkspaceRead(
            id=TEAM_WORKSPACE_ID,
            name="Whadio team",
            is_personal=False,
            my_role=Role.OWNER,
            member_count=3,
            notes_provider=Provider.WHADIO,
            created_at=datetime(2026, 9, 4, 12, 30, tzinfo=UTC),
            default_preset=Preset.DETAILED,
        ),
    )
}


def workspace(workspace_id: UUID) -> WorkspaceRead:
    if workspace_id not in WORKSPACES:
        raise not_found("Workspace")
    return WORKSPACES[workspace_id]


async def seed_demo_user(db: AsyncSession) -> None:
    """Creates Alice and her two workspaces, so the quick start in the API docs works."""
    if await db.scalar(select(User).where(User.email == DEMO_EMAIL)) is not None:
        return
    db.add(
        User(
            user_id=ALICE.id,
            email=ALICE.email,
            name=ALICE.name,
            password_hash=hashlib.sha256((DEMO_EMAIL + DEMO_PASSWORD).encode()).hexdigest(),
            is_administrator=ALICE.is_administrator,
            terms_accepted_at=ALICE.created_at,
            created_at=ALICE.created_at,
        )
    )
    # Same IDs as WORKSPACES, which the meetings stub still reads its demo meetings from.
    for demo in WORKSPACES.values():
        db.add(
            Workspace(
                workspace_id=demo.id,
                name=demo.name,
                default_preset=demo.default_preset,
                is_personal=demo.is_personal,
                created_at=demo.created_at,
            )
        )
        db.add(
            WorkspaceMembership(
                workspace_id=demo.id, user_id=ALICE.id, role=Role.OWNER, joined_at=demo.created_at
            )
        )
    await db.commit()
