from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.app.modules.dashboard.services.morningstar_credentials import build_status, update_token


router = APIRouter(prefix="/api/dashboard/morningstar", tags=["dashboard-morningstar"])

ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
ALLOWED_CLIENT_HOSTS = {"127.0.0.1", "::1", "localhost"}
ALLOWED_ORIGINS = {"http://127.0.0.1:8080", "http://localhost:8080", "http://127.0.0.1:8000", "http://localhost:8000"}


class TokenUpdateRequest(BaseModel):
    md_auth_token: str
    account_hint: str | None = None


def require_local_request(request: Request) -> None:
    host = (request.headers.get("host") or "").split(":", 1)[0].lower()
    origin = request.headers.get("origin")
    client = getattr(request, "client", None)
    client_host = str(getattr(client, "host", "") or "").lower()
    if host not in ALLOWED_HOSTS:
        raise HTTPException(status_code=403, detail="local_host_required")
    if client_host not in ALLOWED_CLIENT_HOSTS:
        raise HTTPException(status_code=403, detail="local_client_required")
    if origin and origin not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="local_origin_required")


@router.get("/token_status")
def morningstar_token_status(request: Request) -> dict[str, Any]:
    require_local_request(request)
    return build_status()


@router.post("/token")
def morningstar_token_update(payload: TokenUpdateRequest, request: Request) -> dict[str, Any]:
    require_local_request(request)
    result = update_token(payload.md_auth_token, payload.account_hint)
    if result.get("status") == "ok":
        return result
    error_type = result.get("error_type")
    status_code = 400
    if error_type in {"provider_failure", "persistence_failure", "dependency_unavailable", "unsupported_callable"}:
        status_code = 503
    elif error_type == "concurrent_update":
        status_code = 409
    raise HTTPException(status_code=status_code, detail=result)
