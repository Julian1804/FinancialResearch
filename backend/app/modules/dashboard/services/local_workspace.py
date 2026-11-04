from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.core.config import PROJECT_ROOT
from backend.app.modules.dashboard.services.morningstar_credentials import morningstar_validation_capability


STATIC_ROOT = PROJECT_ROOT / "frontend_web" / "src" / "dashboard_v1"


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return fallback


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def app_registry() -> dict[str, Any]:
    return _read_json(PROJECT_ROOT / "config" / "fr_app_registry.json", {})


def dashboard_registry() -> dict[str, Any]:
    return _read_json(PROJECT_ROOT / "config" / "fr_dashboard_registry.json", {})


def module_registry() -> dict[str, Any]:
    return _read_json(PROJECT_ROOT / "config" / "fr_module_registry.json", {})


def project_registry() -> dict[str, Any]:
    return _read_json(PROJECT_ROOT / "config" / "fr_project_registry.json", {})


def enabled_apps() -> list[dict[str, Any]]:
    return [row for row in app_registry().get("apps", []) if row.get("enabled")]


def dashboards() -> list[dict[str, Any]]:
    return dashboard_registry().get("dashboards", [])


def modules() -> list[dict[str, Any]]:
    return module_registry().get("modules", [])


def projects() -> list[dict[str, Any]]:
    return project_registry().get("projects", [])


def build_info() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "financial_research_backend",
        "project_root": str(PROJECT_ROOT),
        "static_root": str(STATIC_ROOT),
        "python_exe": sys.executable,
        "served_index_sha256": _sha256(STATIC_ROOT / "index.html"),
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def workspace_bootstrap() -> dict[str, Any]:
    state = user_workspace_state()["state"]
    return {
        "apps": {"apps": enabled_apps()},
        "dashboards": {
            "dashboards": dashboards(),
            "archived_dashboards": [],
            "default_dashboard_count": len(dashboards()),
            "registry_template_dashboard_count": len(dashboards()),
            "user_dashboard_count": 0,
        },
        "modules": {"modules": modules()},
        "user_workspace": {"state": state, "versions": []},
    }


def user_workspace_state() -> dict[str, Any]:
    return {
        "status": "ok",
        "state": {
            "schema_version": "fr_local_user_workspace_state_v1",
            "hidden_registry_dashboard_ids": [],
            "user_dashboards": [],
            "plugin_groups": [],
            "plugin_drafts": [],
            "records": [],
        },
    }


def source_status() -> dict[str, Any]:
    sources: dict[str, Any] = {}
    for app in app_registry().get("apps", []):
        for dep in app.get("connection_dependencies", []) or []:
            sources.setdefault(
                str(dep),
                {
                    "source_id": str(dep),
                    "display_name": str(dep).replace("_", " ").title(),
                    "status": "configured_or_registry_only",
                    "enabled": True,
                    "notes": "Read-only local registry status; no provider call was performed.",
                },
            )
    sources["morningstar_direct"] = {
        "source_id": "morningstar_direct",
        "display_name": "Morningstar Direct / Analytics Lab",
        "status": "credential_capability",
        "enabled": True,
        "credential_capability": morningstar_validation_capability(),
        "notes": "Sanitized local validation capability only; no provider backfill or data download is performed.",
    }
    return {"status": "ok", "sources": sources}


def updateable_products() -> dict[str, Any]:
    products: dict[str, Any] = {}
    for app in app_registry().get("apps", []):
        products[app["app_id"]] = {
            "product_id": app["app_id"],
            "display_name": app["app_name"],
            "status": app.get("status", "registry_only"),
            "can_update": False,
            "user_status_zh": "本地只读状态",
            "user_status_en": "Local read-only status",
            "notes": app.get("notes", ""),
        }
    products["morningstar"] = {
        "product_id": "morningstar",
        "display_name": "Morningstar",
        "status": "credential_status_only",
        "can_update": False,
        "credential_capability": morningstar_validation_capability(),
        "user_status_zh": "仅凭据状态",
        "user_status_en": "Credential status only",
        "notes": "Token validation/replacement is manual and does not run provider backfill.",
    }
    return {"status": "ok", "products": products}


def user_data_catalog() -> dict[str, Any]:
    rows = [
        {
            "data_product_id": "local_registry_workspace",
            "display_name_zh": "本地工作区注册表",
            "display_name_en": "Local Workspace Registries",
            "user_category": "trading",
            "user_category_zh": "研究工作区",
            "user_category_en": "Research Workspace",
            "sub_category": "workspace",
            "source_display_name": "本地配置注册表",
            "source_display_name_en": "Local configuration registries",
            "frequency": "registry",
            "frequency_zh": "注册表",
            "frequency_en": "Registry",
            "coverage_summary_zh": "应用、模块、仪表板和连接状态的只读本地视图。",
            "coverage_summary_en": "Read-only local view of apps, modules, dashboards, and connection status.",
            "observation_grain_zh": "注册表条目",
            "observation_grain_en": "Registry entry",
            "coverage_scope_zh": "本地工作区",
            "coverage_scope_en": "Local workspace",
            "data_layer": "reference_master",
            "data_layer_zh": "参考主数据",
            "data_layer_en": "Reference master",
            "supported_entity_count": len(enabled_apps()) + len(dashboards()) + len(modules()),
            "metric_count": 0,
            "record_count": len(enabled_apps()) + len(dashboards()) + len(modules()),
            "field_count": 8,
            "date_min": "",
            "date_max": "",
            "latest_data_date": "",
            "latest_update_time": "",
            "data_status_label_zh": "可用",
            "data_status_label_en": "Available",
            "available_fields_summary": ["app_id", "dashboard_id", "module_id", "status"],
            "available_fields_summary_en": ["app_id", "dashboard_id", "module_id", "status"],
            "example_entities": ["modeling_workbench", "a_share_main_money_flow", "connections"],
            "user_warning_summary_zh": "此目录是本地只读应用状态，不执行数据更新或提供完整数据覆盖证明。",
            "user_warning_summary_en": "This catalog is local read-only app status; it does not run data updates or prove full data coverage.",
            "open_in_sql_browser_target": None,
            "developer_metadata": {"source": "config registries"},
        }
    ]
    categories = [
        {
            "id": "trading",
            "zh": "研究工作区",
            "en": "Research Workspace",
            "data_product_count": len(rows),
            "support": False,
        },
        {"id": "support", "zh": "计划能力", "en": "Planned Capabilities", "data_product_count": 0, "support": True},
    ]
    return {
        "status": "ok",
        "categories": categories,
        "products": rows,
        "entity_search_index": [],
        "developer_diagnostics": {
            "source": "local_dashboard_api",
            "provider_calls": 0,
            "database_writes": 0,
        },
    }
