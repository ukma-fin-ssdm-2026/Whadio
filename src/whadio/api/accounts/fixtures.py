from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from ..core.errors import not_found
from .schemas import Preset, Provider, Role, UserRead, WorkspaceRead

DEMO_EMAIL: Final = "alice@whadio.dev"
DEMO_PASSWORD: Final = "whadio-demo-pass"
DEMO_SESSION_TOKEN: Final = "demo-browser-session"
DEMO_EXTENSION_TOKEN: Final = "demo-extension-token"

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
