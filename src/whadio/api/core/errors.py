from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Final
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, JsonValue, TypeAdapter, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from ...shared.errors import Failure, RateLimitError, UseCaseError

REQUEST_ID_HEADER = "X-Request-ID"


class ErrorCode(StrEnum):
    EMAIL_MISMATCH = "EMAIL_MISMATCH"
    ACCOUNT_EXISTS = "ACCOUNT_EXISTS"
    NO_NOTES = "NO_NOTES"
    INTEGRATION_UNAVAILABLE = "INTEGRATION_UNAVAILABLE"
    TRANSCRIPT_EXISTS = "TRANSCRIPT_EXISTS"
    ALREADY_PROCESSED = "ALREADY_PROCESSED"
    FOLDER_RECOVERY_CONFLICT = "FOLDER_RECOVERY_CONFLICT"
    DEFAULT_FOLDER = "DEFAULT_FOLDER"
    FOLDER_EXISTS = "FOLDER_EXISTS"
    TERM_EXISTS = "TERM_EXISTS"
    STALE_REVISION = "STALE_REVISION"
    LINK_INVALID = "LINK_INVALID"
    ACCESS_REQUEST_EXISTS = "ACCESS_REQUEST_EXISTS"
    ALREADY_HAS_ACCESS = "ALREADY_HAS_ACCESS"
    ACCESS_REQUEST_NOT_PENDING = "ACCESS_REQUEST_NOT_PENDING"
    SHARE_ALREADY_BOUND = "SHARE_ALREADY_BOUND"
    SHARE_REVOKED = "SHARE_REVOKED"
    MALFORMED_REQUEST = "MALFORMED_REQUEST"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    INSUFFICIENT_ROLE = "INSUFFICIENT_ROLE"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    PERSONAL_WORKSPACE = "PERSONAL_WORKSPACE"
    ALREADY_MEMBER = "ALREADY_MEMBER"
    INVITATION_LIMIT = "INVITATION_LIMIT"
    INVITATION_COOLDOWN = "INVITATION_COOLDOWN"
    INVITATION_NOT_PENDING = "INVITATION_NOT_PENDING"
    NOT_TRANSCRIBED = "NOT_TRANSCRIBED"
    NOTES_IN_PROGRESS = "NOTES_IN_PROGRESS"
    RECORDING_NOT_READY = "RECORDING_NOT_READY"
    RECORDING_DELETED = "RECORDING_DELETED"
    REGENERATION_LIMIT = "REGENERATION_LIMIT"
    CHUNK_MISMATCH = "CHUNK_MISMATCH"
    CAPTURE_CLOSED = "CAPTURE_CLOSED"
    MISSING_CHUNKS = "MISSING_CHUNKS"
    EMPTY_CAPTURE = "EMPTY_CAPTURE"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    RATE_LIMITED = "RATE_LIMITED"
    HTTP_ERROR = "HTTP_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorDetail(BaseModel):
    field: str | None = Field(
        description="Offending input: body field, query or path parameter, or header",
        examples=["email"],
    )
    message: str = Field(
        description="What is wrong with this input",
        examples=["value is not a valid email address"],
    )
    provided_value: JsonValue = Field(
        default=None,
        description="The value the client sent, for a query or path parameter only; body "
        "fields, headers and cookies are never echoed back",
        examples=["500"],
    )


class ErrorBody(BaseModel):
    code: ErrorCode = Field(description="Machine-readable error code to branch on")
    message: str = Field(
        description="Human-readable summary", examples=["Request contains invalid fields"]
    )
    details: list[ErrorDetail] = Field(
        default_factory=list[ErrorDetail],
        description="Per-field problems; empty for errors that concern no single field",
    )
    request_id: str = Field(
        description="Correlation id, also returned in the X-Request-ID header",
        examples=["req_4f9c2a1be07d"],
    )


class ErrorResponse(BaseModel):
    """The single error envelope returned for every 4xx and 5xx response."""

    error: ErrorBody


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        message: str,
        details: Sequence[ErrorDetail] = (),
    ) -> None:
        super().__init__(message)
        self.status_code: int = status_code
        self.code: ErrorCode = code
        self.message: str = message
        self.details: list[ErrorDetail] = list(details)


def not_found(what: str) -> ApiError:
    return ApiError(404, ErrorCode.NOT_FOUND, f"{what} not found")


def error_responses(descriptions: Mapping[int, str]) -> dict[int | str, dict[str, object]]:
    return {
        status: {"model": ErrorResponse, "description": description}
        for status, description in sorted(descriptions.items())
    }


DOC_UNAUTHENTICATED = "`UNAUTHENTICATED`: the session is missing, expired or ended"
DOC_MALFORMED = "`MALFORMED_REQUEST`: the body, or a JSON field in it, is not valid JSON"
DOC_INVALID = "`VALIDATION_ERROR`: a parameter or field is invalid; `details` names each"

# --- Translating every failure into the envelope ---

_LOCATION = TypeAdapter(tuple[str | int, ...])
# A body, header or cookie can carry a password or token; the threat model keeps them out of URLs.
_ECHOED_LOCATIONS: Final = frozenset({"query", "path"})

_FAILURE_MESSAGES: Final[Mapping[Failure, str]] = {
    Failure.EMAIL_MISMATCH: "Sign in with the invited email address",
    Failure.ACCOUNT_EXISTS: "This address has an account; sign in and accept instead",
    Failure.INTEGRATION_UNAVAILABLE: "A service Whadio depends on is unavailable; try again later",
    Failure.NOT_FOUND: "Not found, or you have no access to it",
    Failure.INSUFFICIENT_ROLE: "Your role in this workspace does not allow this",
    Failure.VALIDATION_ERROR: "Request contains invalid fields",
    Failure.TRANSCRIPT_EXISTS: "This meeting already has a transcript",
    Failure.FOLDER_RECOVERY_CONFLICT: "The folder cannot be restored over an existing one",
    Failure.DEFAULT_FOLDER: "The default folder cannot be changed this way",
    Failure.ALREADY_PROCESSED: "This was already processed",
    Failure.INVALID_CREDENTIALS: "Unknown email address or wrong password",
    Failure.PERSONAL_WORKSPACE: "A personal workspace cannot be changed this way",
    Failure.ALREADY_MEMBER: "This email address already belongs to a workspace member",
    Failure.INVITATION_LIMIT: "You have issued too many invitations; try again later",
    Failure.INVITATION_COOLDOWN: "This email address was invited recently; try again later",
    Failure.INVITATION_NOT_PENDING: "This invitation is no longer pending",
    Failure.FOLDER_EXISTS: "A folder with this name already exists",
    Failure.TERM_EXISTS: "This glossary term already exists",
    Failure.NOT_TRANSCRIBED: "The meeting has not been transcribed yet",
    Failure.STALE_REVISION: "The transcript changed since you loaded it",
    Failure.LINK_INVALID: "The link is invalid or has expired",
    Failure.ACCESS_REQUEST_EXISTS: "You have already requested access",
    Failure.ALREADY_HAS_ACCESS: "You already have access",
    Failure.ACCESS_REQUEST_NOT_PENDING: "The access request was already answered",
    Failure.SHARE_ALREADY_BOUND: "The share is already bound to another account",
    Failure.SHARE_REVOKED: "The share was revoked",
    Failure.NOTES_IN_PROGRESS: "Notes are already being written",
    Failure.REGENERATION_LIMIT: "The notes cannot be regenerated again yet",
    Failure.RECORDING_NOT_READY: "The recording is not ready yet",
    Failure.RECORDING_DELETED: "The recording was deleted",
    Failure.CHUNK_MISMATCH: "Different audio is already stored under this chunk number",
    Failure.CAPTURE_CLOSED: "The capture was already completed",
    Failure.MISSING_CHUNKS: "Some chunks never arrived",
    Failure.EMPTY_CAPTURE: "No chunk of the recording arrived",
}

_HTTP_STATUS_CODES: Final[Mapping[int, ErrorCode]] = {
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    413: ErrorCode.PAYLOAD_TOO_LARGE,
}


def register_error_handlers(app: FastAPI) -> None:
    for exception_type in (
        ApiError,
        UseCaseError,
        RequestValidationError,
        StarletteHTTPException,
        Exception,
    ):
        app.add_exception_handler(exception_type, _handle)


async def _handle(_request: Request, exc: Exception) -> JSONResponse:
    status_code, code, message, details = _describe(exc)
    request_id = f"req_{uuid4().hex[:12]}"
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, details=details, request_id=request_id)
    )
    headers = dict(exc.headers or {}) if isinstance(exc, StarletteHTTPException) else {}
    if isinstance(exc, RateLimitError):
        headers["Retry-After"] = str(exc.retry_after)
    if code is ErrorCode.UNAUTHENTICATED:
        headers["WWW-Authenticate"] = 'Session realm="whadio"'
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers={**headers, REQUEST_ID_HEADER: request_id},
    )


def _describe(exc: Exception) -> tuple[int, ErrorCode, str, list[ErrorDetail]]:
    match exc:
        case UseCaseError():
            statuses = {
                Failure.EMAIL_MISMATCH: 403,
                Failure.INVALID_CREDENTIALS: 401,
                Failure.NOT_FOUND: 404,
                Failure.LINK_INVALID: 404,
                Failure.INSUFFICIENT_ROLE: 403,
                Failure.VALIDATION_ERROR: 422,
                Failure.INTEGRATION_UNAVAILABLE: 503,
                Failure.RECORDING_DELETED: 410,
                Failure.INVITATION_LIMIT: 429,
                Failure.INVITATION_COOLDOWN: 429,
            }
            status = statuses.get(exc.code, 409)
            return status, ErrorCode(exc.code.value), _FAILURE_MESSAGES[exc.code], []
        case ApiError():
            return exc.status_code, exc.code, exc.message, exc.details
        case RequestValidationError():
            errors: list[Mapping[str, object]] = list(exc.errors())
            if any(error.get("type") == "json_invalid" for error in errors):
                return (
                    400,
                    ErrorCode.MALFORMED_REQUEST,
                    "The request body, or a JSON field in it, is not valid JSON",
                    [],
                )
            return (
                422,
                ErrorCode.VALIDATION_ERROR,
                "Request contains invalid fields",
                [_validation_detail(error) for error in errors],
            )
        case StarletteHTTPException():
            code = _HTTP_STATUS_CODES.get(exc.status_code, ErrorCode.HTTP_ERROR)
            return exc.status_code, code, str(exc.detail), []
        case _:
            return 500, ErrorCode.INTERNAL_ERROR, "Unexpected server error", []


def _validation_detail(error: Mapping[str, object]) -> ErrorDetail:
    try:
        parts = _LOCATION.validate_python(error.get("loc", ()))
    except ValidationError:
        parts = ()
    is_echoed = bool(parts) and parts[0] in _ECHOED_LOCATIONS and error.get("type") != "missing"
    return ErrorDetail(
        field=".".join(str(part) for part in parts[1:]) or None,
        message=str(error.get("msg", "Invalid value")).removeprefix("Value error, "),
        provided_value=jsonable_encoder(error.get("input")) if is_echoed else None,
    )
