"""Truthful composition root for all currently reachable backend capabilities."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from fastapi import APIRouter, FastAPI

from backend.app.modules.dashboard.routers.local_workspace import router as local_workspace_router
from backend.app.modules.dashboard.routers.morningstar_credentials import router as morningstar_credentials_router
from backend.app.modules.equity_data.routers.query_router import router as china_equity_query_router
from backend.app.modules.equity_data.routers.update_router import router as china_equity_update_router
from backend.app.modules.financial_report.routers.parse_router import router as financial_report_parse_router
from backend.app.modules.system_tasks.routers.first_install_router import router as first_install_bootstrap_router
from backend.app.modules.fund_data.routers.query_router import (
    router as fund_query_router,
    update_router as fund_update_router,
)
from backend.app.modules.research_repository.routers.comparative_series_router import router as comparative_series_router
from backend.app.modules.research_repository.routers.modeling_router import router as modeling_router
from backend.app.modules.system_tasks.routers.operation_lifecycle_router import router as operation_lifecycle_router
from backend.app.modules.system_tasks.routers.data_configuration_router import router as data_configuration_router
from backend.app.modules.system_tasks.routers.installation_router import router as installation_router
from backend.app.modules.system_tasks.routers.data_product_router import router as data_product_router
from backend.app.modules.system_tasks.routers.configured_update_router import router as configured_update_router


CapabilityRole = Literal["v1_serving", "v1_update", "local_operational", "review_tooling"]


@dataclass(frozen=True)
class BackendCapability:
    capability_id: str
    role: CapabilityRole
    route_prefix: str
    router: APIRouter


BACKEND_CAPABILITIES = (
    BackendCapability("local_workspace", "local_operational", "/api", local_workspace_router),
    BackendCapability("morningstar_credentials", "local_operational", "/api/dashboard/morningstar", morningstar_credentials_router),
    BackendCapability("financial_report_parse", "review_tooling", "/api/financial-report/parse", financial_report_parse_router),
    BackendCapability("china_equity_update", "v1_update", "/api/data-console/equity/china", china_equity_update_router),
    BackendCapability("configured_update", "v1_update", "/api/data-console/update", configured_update_router),
    BackendCapability("first_install_bootstrap", "v1_update", "/api/data-console/first-install", first_install_bootstrap_router),
    BackendCapability("china_public_fund", "v1_serving", "/api/funds", fund_query_router),
    BackendCapability("china_public_fund_update", "v1_update", "/api/funds/update", fund_update_router),
    BackendCapability("china_equity", "v1_serving", "/api/equity/china", china_equity_query_router),
    BackendCapability("comparative_series_research", "v1_serving", "/api/research", comparative_series_router),
    BackendCapability("modeling_stage1", "v1_serving", "/api/research/modeling", modeling_router),
    BackendCapability("operation_lifecycle", "v1_serving", "/api/data-console/operation-lifecycle", operation_lifecycle_router),
    BackendCapability("data_configuration", "v1_serving", "/api/data-console/data-configuration", data_configuration_router),
    BackendCapability("installation_bootstrap", "local_operational", "/api/data-console/installation", installation_router),
    BackendCapability("release_bound_data_product", "v1_serving", "/api/data-product", data_product_router),
)


def register_backend_capabilities(app: FastAPI) -> None:
    for capability in BACKEND_CAPABILITIES:
        app.include_router(capability.router)


def capability_catalog() -> dict[str, object]:
    return {
        "schema_version": "fr_backend_capability_catalog_v1",
        "capabilities": [
            {key: value for key, value in asdict(capability).items() if key != "router"}
            for capability in BACKEND_CAPABILITIES
        ],
        "current_v1_serving_authority": ["china_public_fund", "china_equity"],
    }
