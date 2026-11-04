"""One user-intent Update entry for all configured supported check scopes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from backend.app.core.configured_update import run_configured_update
from backend.app.core.diagnostics import new_operation_id
from backend.app.core.operation_lifecycle import lifecycle_read_model
from backend.app.core.storage_profile import PROJECT_ROOT


router = APIRouter(prefix="/api/data-console", tags=["data-update"])


@router.post("/update")
def update_configured_data() -> dict[str, Any]:
    """The caller supplies intent only; configuration freezes the denominator."""
    operation_id = new_operation_id("configured_update")
    try:
        return run_configured_update(operation_id=operation_id, project_root=PROJECT_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={
            "code": "configured_update_unavailable", "operation_id": operation_id,
            "message": str(exc),
        }) from exc
    except Exception as exc:
        status = lifecycle_read_model(operation_id=operation_id)
        operations = status.get("operations") or []
        if operations and operations[0].get("status") == "published":
            return {
                "status": "published", "operation_id": operation_id,
                "active_serving": status["active_serving"],
                "scope_results": (operations[0].get("detail") or {}).get("scope_results", {}),
                "response_recovered_from_durable_publication": True,
            }
        raise HTTPException(status_code=503, detail={
            "code": "configured_update_failed", "operation_id": operation_id,
            "message": "the update did not complete; inspect operation status for scoped results",
            "error_type": type(exc).__name__,
        }) from exc
