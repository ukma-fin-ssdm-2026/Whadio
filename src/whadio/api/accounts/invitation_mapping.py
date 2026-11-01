from ...accounts.models import Invitation
from ...accounts.repositories import WorkspaceInvitation
from .schemas import InvitationRead, InvitationState, InvitedRole


def invitation_read(
    invitation: Invitation | WorkspaceInvitation, *, link_active: bool
) -> InvitationRead:
    return InvitationRead(
        id=invitation.invitation_id,
        email=invitation.invited_email,
        role=InvitedRole(invitation.role.value.lower()),
        status=InvitationState(invitation.status.value),
        created_at=invitation.created_at,
        expires_at=invitation.expires_at,
        link_active=link_active,
    )
