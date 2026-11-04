"""Application-level request, operation, and error diagnostics.

Financial/domain error codes remain owned by their services. This module adds
one small cross-capability classification and correlation boundary without
changing the existing public ``detail.code``/``detail.message`` envelopes.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum
from typing import Any, Iterator, Mapping

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse

from backend.app.core.diagnostic_safety import redact_value, safe_exception_message


LOGGER = logging.getLogger("fr.backend")
REQUEST_ID_HEADER = "X-FR-Request-ID"
OPERATION_ID_HEADER = "X-FR-Operation-ID"
ERROR_CLASS_HEADER = "X-FR-Error-Class"

_request_id: ContextVar[str | None] = ContextVar("fr_request_id", default=None)
_operation_id: ContextVar[str | None] = ContextVar("fr_operation_id", default=None)


class ErrorClass(str, Enum):
    REQUEST_INVALID = "request_invalid"
    SEMANTIC_UNSUPPORTED = "semantic_unsupported"
    IDENTITY_UNRESOLVED_OR_AMBIGUOUS = "identity_unresolved_or_ambiguous"
    DATA_UNAVAILABLE = "data_unavailable"
    PROVIDER_OR_UPDATE_FAILED = "provider_or_update_failed"
    SERVING_STATE_INVALID = "serving_state_invalid"
    CONFLICT_OR_BUSY = "conflict_or_busy"
    INTERNAL_FAILURE = "internal_failure"
    CONTROL_PLANE_UNAVAILABLE = "control_plane_unavailable"


_SEMANTIC_CODES = {"unsupported_adjustment_basis", "unsupported_metric", "invalid_subject_type"}
_IDENTITY_CODES = {
    "ambiguous_listing_episode",
    "ambiguous_series",
    "fund_identity_review_required",
    "identity_crosswalk_missing",
    "identity_owner_invalid",
    "listing_not_found",
}
_SERVING_CODES = {
    "active_release_unavailable",
    "first_publication_pending",
    "china_equity_component_unavailable",
    "china_equity_contract_invalid",
    "china_equity_metadata_unavailable",
    "database_generation_mismatch",
    "fund_component_mismatch",
    "fund_component_unavailable",
    "fund_release_contract_invalid",
    "fund_snapshot_control_hash_mismatch",
    "fund_snapshot_hash_mismatch",
    "fund_snapshot_identity_mismatch",
    "fund_snapshot_not_queryable",
    "fund_snapshot_unavailable",
    "release_binding_unavailable",
    "release_unavailable",
    "snapshot_binding_conflict",
    "snapshot_identity_mismatch",
}
_CONFLICT_CODES = {"china_equity_update_already_running", "a_share_update_already_running"}
_CONFIGURATION_CODES = {"no_data_scope_configured"}
_CONTROL_PLANE_CODES = {"operation_registration_unavailable"}


def new_operation_id(namespace: str) -> str:
    safe_namespace = "".join(character for character in namespace if character.isalnum() or character in "_-")
    return f"{safe_namespace or 'operation'}_{uuid.uuid4().hex}"


def current_request_id() -> str | None:
    return _request_id.get()


def current_operation_id() -> str | None:
    return _operation_id.get()


@contextmanager
def operation_context(operation_id: str) -> Iterator[None]:
    token = _operation_id.set(operation_id)
    try:
        yield
    finally:
        _operation_id.reset(token)


def classify_error(code: str | None, status_code: int) -> ErrorClass:
    normalized = str(code or "").strip().lower()
    if normalized in _CONTROL_PLANE_CODES:
        return ErrorClass.CONTROL_PLANE_UNAVAILABLE
    if normalized in _CONFIGURATION_CODES:
        return ErrorClass.REQUEST_INVALID
    if normalized in _SEMANTIC_CODES or normalized.startswith("unsupported_"):
        return ErrorClass.SEMANTIC_UNSUPPORTED
    if normalized in _IDENTITY_CODES or "ambiguous" in normalized or normalized.startswith("identity_"):
        return ErrorClass.IDENTITY_UNRESOLVED_OR_AMBIGUOUS
    if normalized in _SERVING_CODES or any(token in normalized for token in ("release_", "snapshot_", "generation_")):
        return ErrorClass.SERVING_STATE_INVALID
    if normalized in _CONFLICT_CODES or status_code == 409 or "busy" in normalized:
        return ErrorClass.CONFLICT_OR_BUSY
    if normalized.startswith("fund_update_") or any(token in normalized for token in ("provider", "source_refresh", "update_failed")):
        return ErrorClass.PROVIDER_OR_UPDATE_FAILED
    if status_code == 404 or any(token in normalized for token in ("not_found", "unavailable", "no_data", "empty")):
        return ErrorClass.DATA_UNAVAILABLE
    if status_code in {400, 405, 422} or normalized.startswith("invalid_") or normalized.startswith("explicit_"):
        return ErrorClass.REQUEST_INVALID
    return ErrorClass.INTERNAL_FAILURE


def _safe_value(value: Any) -> Any:
    return redact_value(value)


def log_event(event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    payload = {
        "event": event,
        "request_id": current_request_id(),
        "operation_id": current_operation_id(),
        **{key: _safe_value(value) for key, value in fields.items()},
    }
    LOGGER.log(level, json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def log_serving_binding(capability: str, metadata: Mapping[str, Any]) -> None:
    log_event(
        "serving_binding_resolved",
        capability=capability,
        stage="serving_resolution",
        release_id=metadata.get("release_id"),
        snapshot_id=metadata.get("snapshot_id"),
        database_generation_id=metadata.get("database_generation_id"),
        binding_id=metadata.get("binding_id"),
    )


def diagnostic_http_exception(exc: Any) -> HTTPException:
    classification = classify_error(getattr(exc, "code", None), int(getattr(exc, "status_code", 500)))
    headers = {ERROR_CLASS_HEADER: classification.value}
    if current_operation_id():
        headers[OPERATION_ID_HEADER] = current_operation_id() or ""
    return HTTPException(
        status_code=int(getattr(exc, "status_code", 500)),
        detail={"code": str(getattr(exc, "code", "internal_failure")), "message": safe_exception_message(exc)},
        headers=headers,
    )


def diagnostic_result_http_exception(
    result: Mapping[str, Any],
    *,
    status_code: int,
    code: str,
) -> HTTPException:
    """Convert a completed operation result into a truthful HTTP failure."""
    payload = dict(result)
    payload.setdefault("code", code)
    payload.setdefault("message", safe_exception_message(payload.get("error") or payload.get("result") or code))
    payload = redact_value(payload)
    classification = classify_error(code, status_code)
    payload.setdefault("error_class", classification.value)
    headers = {ERROR_CLASS_HEADER: classification.value}
    operation_id = payload.get("operation_id") or current_operation_id()
    if operation_id:
        headers[OPERATION_ID_HEADER] = str(operation_id)
    return HTTPException(status_code=status_code, detail=payload, headers=headers)


def install_diagnostic_boundary(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def classified_http_exception(request: Request, exc: HTTPException):
        safe_detail = redact_value(exc.detail)
        detail = safe_detail if isinstance(safe_detail, Mapping) else {}
        code = str(detail.get("code") or "http_error")
        classification = classify_error(code, exc.status_code)
        log_event(
            "request_error",
            level=logging.WARNING if exc.status_code < 500 else logging.ERROR,
            method=request.method,
            path=request.url.path,
            stage="request_handling",
            status_code=exc.status_code,
            error_class=classification.value,
            error_code=code,
        )
        safe_exc = HTTPException(
            status_code=exc.status_code,
            detail=safe_detail,
            headers=exc.headers,
        )
        response = await http_exception_handler(request, safe_exc)
        response.headers.setdefault(ERROR_CLASS_HEADER, classification.value)
        if current_request_id():
            response.headers.setdefault(REQUEST_ID_HEADER, current_request_id() or "")
        return response

    @app.exception_handler(RequestValidationError)
    async def classified_request_validation(request: Request, exc: RequestValidationError):
        log_event(
            "request_error",
            level=logging.WARNING,
            method=request.method,
            path=request.url.path,
            stage="request_validation",
            status_code=422,
            error_class=ErrorClass.REQUEST_INVALID.value,
            error_code="request_validation_failed",
            validation_error_count=len(exc.errors()),
        )
        safe_errors = redact_value(exc.errors())
        safe_body = redact_value(getattr(exc, "body", None))
        safe_exc = RequestValidationError(safe_errors, body=safe_body)
        response = await request_validation_exception_handler(request, safe_exc)
        response.headers[ERROR_CLASS_HEADER] = ErrorClass.REQUEST_INVALID.value
        if current_request_id():
            response.headers[REQUEST_ID_HEADER] = current_request_id() or ""
        return response

    @app.middleware("http")
    async def request_diagnostic_boundary(request: Request, call_next):
        request_id = new_operation_id("request")
        token = _request_id.set(request_id)
        started = time.monotonic()
        log_event("request_started", method=request.method, path=request.url.path, stage="request_received")
        try:
            response = await call_next(request)
        except Exception as exc:
            log_event(
                "request_failed",
                level=logging.ERROR,
                method=request.method,
                path=request.url.path,
                stage="request_handling",
                error_class=ErrorClass.INTERNAL_FAILURE.value,
                error_code=type(exc).__name__,
                duration_ms=round((time.monotonic() - started) * 1000, 3),
            )
            headers = {
                REQUEST_ID_HEADER: request_id,
                ERROR_CLASS_HEADER: ErrorClass.INTERNAL_FAILURE.value,
            }
            if current_operation_id():
                headers[OPERATION_ID_HEADER] = current_operation_id() or ""
            return PlainTextResponse("Internal Server Error", status_code=500, headers=headers)
        else:
            response.headers.setdefault(REQUEST_ID_HEADER, request_id)
            log_event(
                "request_completed",
                method=request.method,
                path=request.url.path,
                route=getattr(request.scope.get("route"), "path", None),
                stage="response_ready",
                status_code=response.status_code,
                error_class=response.headers.get(ERROR_CLASS_HEADER),
                duration_ms=round((time.monotonic() - started) * 1000, 3),
            )
            return response
        finally:
            _request_id.reset(token)
