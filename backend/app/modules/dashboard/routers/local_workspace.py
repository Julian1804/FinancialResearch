from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from backend.app.modules.dashboard.services import local_workspace


router = APIRouter(prefix="/api", tags=["dashboard-local-workspace"])


@router.get("/debug/build_info")
def debug_build_info() -> dict[str, Any]:
    return local_workspace.build_info()


@router.get("/workspace/bootstrap")
def workspace_bootstrap() -> dict[str, Any]:
    return local_workspace.workspace_bootstrap()


@router.get("/workspace/apps/list")
def workspace_apps_list() -> dict[str, Any]:
    return {"status": "ok", "apps": local_workspace.enabled_apps()}


@router.get("/workspace/dashboards/list")
def workspace_dashboards_list() -> dict[str, Any]:
    dashboards = local_workspace.dashboards()
    return {
        "status": "ok",
        "dashboards": dashboards,
        "archived_dashboards": [],
        "default_dashboard_count": len(dashboards),
        "registry_template_dashboard_count": len(dashboards),
        "user_dashboard_count": 0,
    }


@router.get("/workspace/dashboards/detail")
def workspace_dashboard_detail(id: str) -> dict[str, Any]:
    for dashboard in local_workspace.dashboards():
        if dashboard.get("dashboard_id") == id:
            return {"status": "ok", "dashboard": dashboard}
    raise HTTPException(status_code=404, detail="dashboard_not_found")


@router.get("/modules/list")
def modules_list() -> dict[str, Any]:
    return {"status": "ok", "modules": local_workspace.modules()}


@router.get("/modules/detail")
def modules_detail(module_id: str) -> dict[str, Any]:
    for module in local_workspace.modules():
        if module.get("module_id") == module_id:
            return {"status": "ok", "module": module, "data_series": module.get("data_series", [])}
    raise HTTPException(status_code=404, detail="module_not_found")


@router.get("/modules/summary")
def modules_summary(module_id: str) -> dict[str, Any]:
    for module in local_workspace.modules():
        if module.get("module_id") == module_id:
            return {
                "status": "ok",
                "module_id": module_id,
                "summary_cards": [
                    {"label": "Status", "value": module.get("status", "available_read_only")},
                    {"label": "Source status", "value": module.get("source_status", "registry_only")},
                    {"label": "QA status", "value": module.get("qa_status", "registry_only")},
                ],
            }
    raise HTTPException(status_code=404, detail="module_not_found")


@router.get("/projects/list")
def projects_list() -> dict[str, Any]:
    return {"status": "ok", "projects": local_workspace.projects()}


@router.get("/data_console/source_status")
def data_console_source_status() -> dict[str, Any]:
    return local_workspace.source_status()


@router.get("/data_console/updateable_products")
def data_console_updateable_products() -> dict[str, Any]:
    return local_workspace.updateable_products()


@router.get("/research-workspace/user-data-catalog")
def research_workspace_user_data_catalog() -> dict[str, Any]:
    return local_workspace.user_data_catalog()


@router.get("/research-workspace/status")
def research_workspace_status() -> dict[str, Any]:
    return {"status": "ok", "mode": "local_read_only", "database_writes_enabled": False}
