import logging

import starlette.exceptions
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse


class AppError(Exception):
    def __init__(self, message: str, status_code: int, code: str):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


def register_error_handlers(app: FastAPI, logger: logging.Logger) -> None:
    """Register error handlers for the app."""

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        logger.warning(exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(starlette.exceptions.HTTPException)
    async def http_error_handler(
        request: Request, exc: starlette.exceptions.HTTPException
    ) -> JSONResponse:
        logger.warning(f"HTTP Error {exc.status_code}")
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": "HTTP_ERROR", "message": exc.detail}},
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Internal server error", extra={"error_type": type(exc).__name__})
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": "Internal server error"}},
        )
