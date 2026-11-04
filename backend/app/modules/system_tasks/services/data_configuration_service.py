"""Explicit current-configuration transition for an existing installation."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any, Mapping

from backend.app.core.desired_data_profile import DesiredDataProfileRepository, desired_data_profile_from_payload
from backend.app.core.storage_profile import resolve_active_snapshot_pointer, resolve_control_plane_path
from backend.app.core.writer_runtime_ownership import WriterBusyError, acquire_writer_lease


class ExistingInstallationConfigurationError(RuntimeError):
    code = "existing_install_configuration_unavailable"
    status_code = 409


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def establish_existing_install_configuration(
    payload: Mapping[str, Any],
    *,
    repository: DesiredDataProfileRepository | None = None,
    control_path: Path | None = None,
    active_pointer: Path | None = None,
    operation_id: str | None = None,
) -> dict[str, Any]:
    """Persist explicit desired intent as the current authority on a serving install.

    This is deliberately separate from First Install.  The active pointer is a
    precondition proving that this is an existing installation, while the
    supplied profile is the only source of user intent.  The repository write
    is one transaction under the installation writer lease; no provider,
    business-data, identity, head, or publication owner is called.
    """
    pointer = Path(active_pointer) if active_pointer is not None else resolve_active_snapshot_pointer()
    if not pointer.is_file():
        raise ExistingInstallationConfigurationError(
            "an Active Data Snapshot is required for an existing-install configuration transition"
        )
    profile_value = payload.get("profile")
    if not isinstance(profile_value, Mapping):
        raise ValueError("profile is required")
    profile = desired_data_profile_from_payload(profile_value)
    database_path = Path(control_path) if control_path is not None else resolve_control_plane_path()
    repository = repository or DesiredDataProfileRepository(database_path)
    before = repository.current_configuration()
    selected_operation_id = operation_id or f"configuration_transition_{uuid.uuid4().hex}"
    pointer_before = _sha256(pointer)
    lease = acquire_writer_lease(operation_id=selected_operation_id, database_path=database_path)
    try:
        # Re-read the serving precondition after acquiring the same writer
        # ownership used by updates/publication.
        if not pointer.is_file():
            raise ExistingInstallationConfigurationError(
                "the Active Data Snapshot disappeared before configuration could be committed"
            )
        persisted = repository.put(profile, make_current=True)
        after = repository.current_configuration()
        return {
            "status": "configured",
            "result": "current_configuration_established",
            "operation_id": selected_operation_id,
            "transition": "existing_install_current_configuration",
            "configuration_before": before,
            "configuration_after": after,
            "profile": persisted,
            "active_pointer_before_sha256": pointer_before,
            "active_pointer_after_sha256": _sha256(pointer),
            "provider_calls": 0,
            "business_data_writes": 0,
            "identity_mutations": 0,
            "validated_head_transitions": 0,
            "publication_attempted": False,
            "first_install_invoked": False,
        }
    finally:
        lease.release(status="released")

