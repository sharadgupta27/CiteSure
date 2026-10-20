"""Domain exceptions. Services raise these; one handler in main.py maps them to HTTP errors.

A resource the caller may not read is reported as NotFound (404), never Forbidden, so
the existence of restricted documents is not leaked.
"""

from __future__ import annotations


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, detail: str = "") -> None:
        super().__init__(detail or self.code)
        self.detail = detail or self.code.replace("_", " ")


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class PayloadTooLarge(AppError):
    status_code = 413
    code = "payload_too_large"


class UnsupportedMedia(AppError):
    status_code = 415
    code = "unsupported_media_type"


class TooManyRequests(AppError):
    status_code = 429
    code = "rate_limited"


class InvalidInput(AppError):
    status_code = 422
    code = "invalid_input"


class UpstreamError(AppError):
    status_code = 502
    code = "upstream_error"
