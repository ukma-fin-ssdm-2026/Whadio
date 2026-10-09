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

REQUEST_ID_HEADER = "X-Request-ID"


class ErrorCode(StrEnum):
    MALFORMED_REQUEST = "MALFORMED_REQUEST"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    INSUFFICIENT_ROLE = "INSUFFICIENT_ROLE"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    PERSONAL_WORKSPACE = "PERSONAL_WORKSPACE"
    NOT_TRANSCRIBED = "NOT_TRANSCRIBED"
    NOTES_IN_PROGRESS = "NOTES_IN_PROGRESS"
    REGENERATION_LIMIT = "REGENERATION_LIMIT"
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
        description="The value the client sent, when it is safe to echo back",
        examples=["alice@"],
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

_HTTP_STATUS_CODES: Final[Mapping[int, ErrorCode]] = {
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
}


def register_error_handlers(app: FastAPI) -> None:
    for exception_type in (ApiError, RequestValidationError, StarletteHTTPException, Exception):
        app.add_exception_handler(exception_type, _handle)


async def _handle(_request: Request, exc: Exception) -> JSONResponse:
    status_code, code, message, details = _describe(exc)
    request_id = f"req_{uuid4().hex[:12]}"
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, details=details, request_id=request_id)
    )
    headers = dict(exc.headers or {}) if isinstance(exc, StarletteHTTPException) else {}
    if code is ErrorCode.UNAUTHENTICATED:
        headers["WWW-Authenticate"] = 'Session realm="whadio"'
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers={**headers, REQUEST_ID_HEADER: request_id},
    )


def _describe(exc: Exception) -> tuple[int, ErrorCode, str, list[ErrorDetail]]:
    match exc:
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
    is_missing = error.get("type") == "missing"
    return ErrorDetail(
        field=".".join(str(part) for part in parts[1:]) or None,
        message=str(error.get("msg", "Invalid value")).removeprefix("Value error, "),
        provided_value=None if is_missing else jsonable_encoder(error.get("input")),
    )
