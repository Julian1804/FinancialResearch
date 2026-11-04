from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from backend.app.core.operation_lifecycle import SCOPES, lifecycle_read_model
from backend.app.core.diagnostic_safety import safe_exception_message


router = APIRouter(prefix="/api/data-console/operation-lifecycle", tags=["operation-lifecycle"])


@router.get("")
def operation_lifecycle(
    scope: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    snapshot_id: str | None = Query(default=None),
    release_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Read current serving and recent product-operation lifecycle facts."""
    if scope is not None and scope not in SCOPES:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_operation_scope", "message": "scope is not a supported operation scope"},
        )
    try:
        return lifecycle_read_model(
            scope=scope,
            limit=limit,
            bound_snapshot_id=snapshot_id,
            bound_release_id=release_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_operation_scope", "message": safe_exception_message(exc)}) from exc


@router.get("/{operation_id}")
def operation_lifecycle_by_id(operation_id: str) -> dict[str, Any]:
    if not operation_id or any(token in operation_id for token in ("/", "\\", "..")):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_operation_id", "message": "operation_id must be one path-safe segment"},
        )
    result = lifecycle_read_model(operation_id=operation_id)
    if not result["operations"]:
        raise HTTPException(
            status_code=404,
            detail={"code": "operation_not_found", "message": "operation lifecycle is not available"},
        )
    return result
