"""Consistent JSON error envelope: {"error": {"code", "message", "details"}} (PRD §8.4)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ZikoError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFound(ZikoError):
    status_code = 404
    code = "not_found"


class Ambiguous(ZikoError):
    """More than one task matches — caller must ask the user (PRD §5.1)."""

    status_code = 409
    code = "ambiguous"


class Validation(ZikoError):
    status_code = 422
    code = "validation_error"


class Conflict(ZikoError):
    status_code = 409
    code = "conflict"


def _envelope(code: str, message: str, details: Any = None, status: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": details}},
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ZikoError)
    async def _ziko(_: Request, exc: ZikoError) -> JSONResponse:
        return _envelope(exc.code, exc.message, exc.details, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _envelope("validation_error", "Invalid request", exc.errors(), 422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found"}.get(exc.status_code, "http_error")
        return _envelope(code, str(exc.detail), None, exc.status_code)
