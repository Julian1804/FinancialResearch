from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from backend.app.core.diagnostic_safety import safe_exception_message
from backend.app.core.diagnostics import diagnostic_result_http_exception
from backend.app.core.first_install_sources import HKEXIdentityReferenceGap
from backend.app.core.operation_lifecycle import OperationRegistrationUnavailable
from backend.app.modules.system_tasks.services.first_install_service import (
    first_install_status,
    run_first_install,
)


router = APIRouter(prefix="/api/data-console/first-install", tags=["first-install-bootstrap"])


@router.get("/status/{profile_id}")
def status(profile_id: str) -> dict[str, Any]:
    return first_install_status(profile_id)


@router.post("/run")
def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return run_first_install(payload)
    except OperationRegistrationUnavailable as exc:
        raise diagnostic_result_http_exception(
            {
                "status": "rejected",
                "result": "operation_registration_unavailable",
                "operation_accepted": False,
                "retryable": True,
                "error_code": "operation_registration_unavailable",
                "error_class": "control_plane_unavailable",
                "error": "the operation could not be durably registered; no financial work was started",
            },
            status_code=503,
            code="operation_registration_unavailable",
        ) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_first_install_request", "message": safe_exception_message(exc)}) from exc
    except HKEXIdentityReferenceGap as exc:
        raise HTTPException(status_code=409, detail={"code": "identity_reference_gap", "message": safe_exception_message(exc)}) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail={"code": "first_install_unavailable", "message": safe_exception_message(exc)}) from exc
