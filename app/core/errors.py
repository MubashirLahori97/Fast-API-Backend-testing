"""One error format for every response, so the apps can show messages under the right field.

    {"error": {"code": "email_taken", "message": "An account with this ...", "field": "email"}}

Validation errors also carry "details": one {"field", "message"} entry per problem.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

# Story 9.2's "Action failed" message, used wherever an action fails for a reason the client
# can't fix but can retry.
ACTION_FAILED = "We couldn’t do that just now. Please try again."


class AppError(Exception):
    """An error meant for the client. Raise it from any endpoint or service:

    raise AppError(409, "email_taken", "An account with this email already exists.", field="email")
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        field: str | None = None,
        details: list[dict] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field = field
        # One {"field", "message"} entry per problem, as in validation errors.
        self.details = details


@contextmanager
def database_errors_retryable(db: Session) -> Iterator[None]:
    """Turns any database error inside the block (a lock, a query, the commit) into a 503 with
    ACTION_FAILED. The error's own text isn't logged or returned: Postgres can put a row's
    values in it ("Failing row contains ..."), and those can be health data."""
    try:
        yield
    except SQLAlchemyError:
        db.rollback()
        raise AppError(503, "save_failed", ACTION_FAILED) from None


def error_body(code: str, message: str, field: str | None = None, **extra: Any) -> dict:
    return {"error": {"code": code, "message": message, "field": field, **extra}}


def _field_name(loc: tuple) -> str | None:
    # loc looks like ("body", "email"); the first part only says where the field came from.
    return ".".join(str(part) for part in loc[1:]) or None


def _message(error: dict) -> str:
    # Pydantic prefixes messages raised by our own validators with "Value error, ".
    return error["msg"].removeprefix("Value error, ")


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(
                exc.code,
                exc.message,
                exc.field,
                **({"details": exc.details} if exc.details else {}),
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [{"field": _field_name(e["loc"]), "message": _message(e)} for e in exc.errors()]
        first = details[0]
        body = error_body("validation_error", first["message"], first["field"], details=details)
        return JSONResponse(status_code=422, content=body)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = HTTPStatus(exc.status_code).phrase.lower().replace(" ", "_")
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, str(exc.detail)),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # The server still logs the traceback; the client never sees internal details.
        return JSONResponse(
            status_code=500,
            content=error_body("internal_error", "Something went wrong. Please try again."),
            # Set here because this handler runs outside the app's middleware (NoStore).
            headers={"Cache-Control": "no-store"},
        )
