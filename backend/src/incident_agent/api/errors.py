"""One error shape for every endpoint: `{"error": {"code", "message", ...}}`."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from incident_agent.api.schemas import ErrorResponse

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.headers, self.extra = headers, extra


def error_response(
    status: int, code: str, message: str, headers: dict[str, str] | None = None, **extra: Any
) -> JSONResponse:
    body = {"error": {"code": code, "message": message, **extra}}
    return JSONResponse(body, status_code=status, headers=headers)


# For the `responses=` of routes, so the contract lists the error shape.
ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse, "description": text}
    for status, text in {
        404: "Not found",
        422: "Invalid request",
        429: "Daily limit reached",
        503: "Unavailable",
    }.items()
}


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message, exc.headers, **exc.extra)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {"field": ".".join(str(p) for p in err["loc"][1:]) or str(err["loc"][0]),
             "message": str(err["msg"]).removeprefix("Value error, ")}
            for err in exc.errors()
        ]  # fmt: skip
        return error_response(422, "invalid_request", "The request is not valid.", fields=fields)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed", 413: "too_large"}.get(
            exc.status_code, "error"
        )
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(SQLAlchemyError)
    async def _database(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        log.error("database error: %s", type(exc).__name__)
        return error_response(503, "database_unavailable", "The database is unavailable.")

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return error_response(500, "internal_error", "Something went wrong.")
