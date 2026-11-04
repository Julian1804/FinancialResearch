from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from backend.app.core.installation_bootstrap import (
    bootstrap_path,
    load_installation_bootstrap,
    select_data_root,
    validate_data_root,
)
from backend.app.core.diagnostic_safety import safe_exception_message
from backend.app.core.storage_capacity import capacity_decision, estimate_storage_requirement
from backend.app.core.storage_profile import resolve_active_snapshot_pointer


router = APIRouter(prefix="/api/data-console/installation", tags=["installation-bootstrap"])


@router.get("/status")
def status() -> dict[str, Any]:
    value = load_installation_bootstrap()
    selected = value.get("selected_data_root")
    capacity = None
    if value.get("status") == "selected" and selected:
        try:
            capacity = validate_data_root(str(selected), create=False)
        except ValueError as exc:
            capacity = {"status": "invalid", "error": safe_exception_message(exc)}
    return {**value, "bootstrap_path": str(bootstrap_path()), "capacity": capacity}


@router.post("/data-root/validate")
def validate(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return {"status": "valid", "capacity": validate_data_root(str(payload.get("data_root") or ""), create=False)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_data_root", "message": safe_exception_message(exc)}) from exc


@router.post("/data-root/select")
def select(payload: dict[str, Any]) -> dict[str, Any]:
    if resolve_active_snapshot_pointer().is_file():
        raise HTTPException(status_code=409, detail={"code": "data_root_selection_locked", "message": "data root cannot change after publication"})
    try:
        return select_data_root(str(payload.get("data_root") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_data_root", "message": safe_exception_message(exc)}) from exc


@router.post("/capacity-estimate")
def capacity_estimate(payload: dict[str, Any]) -> dict[str, Any]:
    profile = payload.get("profile")
    if not isinstance(profile, dict):
        raise HTTPException(status_code=400, detail={"code": "invalid_capacity_request", "message": "profile is required"})
    data_root = str(payload.get("data_root") or "").strip()
    if data_root:
        try:
            info = validate_data_root(data_root, create=False)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "invalid_data_root", "message": safe_exception_message(exc)}) from exc
        return capacity_decision(profile, free_bytes=int(info["free_bytes"]))
    try:
        estimate = estimate_storage_requirement(profile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_capacity_request", "message": safe_exception_message(exc)}) from exc
    return {**estimate, "decision": "select_data_root_first"}
