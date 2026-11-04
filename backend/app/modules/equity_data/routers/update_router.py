from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.app.core.diagnostics import diagnostic_result_http_exception
from backend.app.modules.equity_data.services.china_equity_update_service import (
    check_update_state,
    run_user_triggered_china_equity_update,
)


router = APIRouter(prefix="/api/data-console", tags=["data-update"])


@router.get("/equity/china/update-state")
def china_equity_update_state() -> dict[str, Any]:
    return check_update_state()


@router.post("/equity/china/update")
def update_china_equity() -> dict[str, Any]:
    return _run_update(legacy=False)


def _run_update(*, legacy: bool) -> dict[str, Any]:
    """User intent entry; no ticker, metric, date, or work package is accepted."""
    result = run_user_triggered_china_equity_update()
    if result.get("status") == "busy":
        raise diagnostic_result_http_exception(
            result, status_code=409, code="a_share_update_already_running" if legacy else "china_equity_update_already_running"
        )
    if result.get("error_code") == "no_data_scope_configured":
        raise diagnostic_result_http_exception(
            result, status_code=409, code="no_data_scope_configured"
        )
    if result.get("error_code") == "operation_registration_unavailable":
        raise diagnostic_result_http_exception(
            result, status_code=503, code="operation_registration_unavailable"
        )
    if result.get("status") != "success":
        raise diagnostic_result_http_exception(
            result, status_code=503, code="a_share_update_failed" if legacy else "china_equity_update_failed"
        )
    return result


@router.get("/a-share/update-state", include_in_schema=False)
def a_share_update_state() -> dict[str, Any]:
    """Compatibility alias for the former public update-state URL."""
    return china_equity_update_state()


@router.post("/a-share/update", include_in_schema=False)
def update_a_share() -> dict[str, Any]:
    """Compatibility alias for the former public update URL."""
    return _run_update(legacy=True)
