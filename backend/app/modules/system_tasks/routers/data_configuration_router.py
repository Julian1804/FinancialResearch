from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from backend.app.core.diagnostic_safety import safe_exception_message
from backend.app.core.desired_data_profile import DesiredDataProfileRepository
from backend.app.core.diagnostics import diagnostic_http_exception
from backend.app.core.storage_profile import resolve_control_plane_path
from backend.app.core.writer_runtime_ownership import WriterBusyError
from backend.app.modules.system_tasks.services.data_configuration_service import (
    ExistingInstallationConfigurationError,
    establish_existing_install_configuration,
)


router = APIRouter(prefix="/api/data-console/data-configuration", tags=["data-configuration"])


@router.get("")
def data_configuration() -> dict[str, Any]:
    """Read the installation's current data-configuration authority."""
    return DesiredDataProfileRepository(resolve_control_plane_path()).current_configuration()


@router.post("")
def establish_data_configuration(payload: dict[str, Any]) -> dict[str, Any]:
    """Establish explicit current intent without invoking First Install or Update."""
    try:
        return establish_existing_install_configuration(payload)
    except ExistingInstallationConfigurationError as exc:
        raise diagnostic_http_exception(exc) from exc
    except WriterBusyError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "installation_writer_busy", "message": "installation writer is busy"},
        ) from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_current_configuration_request", "message": safe_exception_message(exc)}) from exc
