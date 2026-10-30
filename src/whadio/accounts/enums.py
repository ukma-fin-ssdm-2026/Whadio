from enum import StrEnum


class RegistrationMode(StrEnum):
    INVITE_ONLY = "invite-only"
    VERIFIED = "verified"


class WorkspaceRole(StrEnum):
    MEMBER = "Member"
    MODERATOR = "Moderator"
    OWNER = "Owner"


class InvitationRole(StrEnum):
    MEMBER = "Member"
    MODERATOR = "Moderator"


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"


class SessionKind(StrEnum):
    BROWSER = "browser"
    EXTENSION = "extension"


class NotesTemplate(StrEnum):
    SUMMARY = "summary"
    DETAILED = "detailed"
    INTERVIEW = "interview"


class LlmProvider(StrEnum):
    WHADIO = "Whadio"
    ANTHROPIC = "Anthropic"
    OPENAI = "OpenAI"
    GOOGLE = "Google"
