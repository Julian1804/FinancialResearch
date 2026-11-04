"""Application owner for source-driven first-install initialization."""

from __future__ import annotations

import uuid
import os
from datetime import datetime, timezone
from typing import Any, Mapping

from backend.app.core.desired_data_profile import DesiredDataProfileRepository, desired_data_profile_from_payload
from backend.app.core.first_install_bootstrap import FirstInstallPaths, build_initial_snapshot, publish_initial_snapshot
from backend.app.core.first_install_sources import FirstInstallSourceAcquirer, HKEXIdentityReferenceGap
from backend.app.core.diagnostics import current_request_id
from backend.app.core.operation_lifecycle import (
    OperationRegistrationUnavailable,
    record_operation_result,
    record_operation_started,
)
from backend.app.core.writer_runtime_ownership import WriterBusyError, acquire_writer_lease, write_runtime_owner_marker
from backend.app.core.storage_profile import (
    resolve_active_snapshot_pointer,
    resolve_control_plane_path,
    resolve_identity_state_backup_root,
    resolve_identity_state_path,
    resolve_serving_release_registry_path,
    resolve_temporary_workspace_path,
    resolve_unpublished_snapshot_path,
)
from backend.app.core.installation_bootstrap import selected_data_root


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def first_install_status(profile_id: str) -> dict[str, Any]:
    repository = DesiredDataProfileRepository(resolve_control_plane_path())
    return {
        "profile": repository.get(profile_id),
        "active_data_snapshot_available": resolve_active_snapshot_pointer().is_file(),
        "operation_available": not resolve_active_snapshot_pointer().exists(),
    }


def run_first_install(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Execute one bounded bootstrap; caller maps failures to the HTTP model."""
    if os.environ.get("FR_INSTALLATION_BOOTSTRAP_REQUIRED", "").strip() == "1" and selected_data_root() is None:
        raise RuntimeError("data root must be selected before first-install bootstrap")
    if resolve_active_snapshot_pointer().exists():
        raise RuntimeError("first-install bootstrap is unavailable after an Active Data Snapshot exists")
    profile = desired_data_profile_from_payload(dict(payload.get("profile") or {}))
    operation_id = f"first_install_{uuid.uuid4().hex}"
    snapshot_id = f"frbootstrap_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:12]}"
    workspace = resolve_temporary_workspace_path(operation_id)
    # Profile validation and the initial pointer read above are preflight.  The
    # durable operation registration is the acceptance anchor; no writer lease,
    # provider call, or installation mutation is allowed before it succeeds.
    try:
        record_operation_started(
            operation_id,
            operation_type="first_install",
            scope="installation",
            runtime_root=workspace,
            request_id=current_request_id(),
        )
    except OperationRegistrationUnavailable:
        raise
    try:
        writer_lease = acquire_writer_lease(operation_id=operation_id)
    except WriterBusyError as exc:
        try:
            record_operation_result(
                operation_id,
                {
                    "status": "busy",
                    "result": "busy",
                    "error_code": "installation_writer_busy",
                    "error_class": "conflict_or_busy",
                    "retryable": True,
                    "writer_operation_id": exc.record.operation_id,
                },
                operation_type="first_install",
                scope="installation",
            )
        except Exception:
            pass
        raise RuntimeError("installation writer is busy") from exc
    if resolve_active_snapshot_pointer().exists():
        writer_lease.release()
        try:
            record_operation_result(
                operation_id,
                {
                    "status": "failed",
                    "result": "first_install_unavailable",
                    "error_code": "first_install_unavailable",
                    "error_class": "serving_state_invalid",
                    "retryable": False,
                },
                operation_type="first_install",
                scope="installation",
            )
        except Exception:
            pass
        raise RuntimeError("first-install bootstrap is unavailable after an Active Data Snapshot exists")
    # The lease boundary begins before lifecycle/profile/runtime persistence
    # after registration and remains held through source retention, build,
    # publication, and terminal lifecycle persistence because each stage
    # mutates installation state.
    try:
        write_runtime_owner_marker(
            workspace,
            operation_id=operation_id,
            owner_id=operation_id,
            predecessor_snapshot_id=None,
            state="active",
        )
    except Exception:
        # The lifecycle marker is supporting readback evidence; bootstrap
        # publication remains owned by its accepted pipeline.
        pass
    try:
        repository = DesiredDataProfileRepository(resolve_control_plane_path())
        # The profile supplied for a real First-Install run is the user's
        # explicit installation configuration.  Persist it as the current
        # configuration authority; retained named profiles do not become
        # current merely because they remain in the profile table.
        repository.put(profile, make_current=True)
        source_package = FirstInstallSourceAcquirer(workspace / "source").acquire(
            profile, run_id=operation_id, as_of_date=str(payload.get("as_of_date") or datetime.now(timezone.utc).date().isoformat()),
        )
        try:
            write_runtime_owner_marker(
                workspace,
                operation_id=operation_id,
                owner_id=operation_id,
                predecessor_snapshot_id=None,
                state="active",
            )
        except Exception:
            pass
        paths = FirstInstallPaths(
            snapshots_root=resolve_unpublished_snapshot_path(snapshot_id).parent,
            identity_path=resolve_identity_state_path(),
            identity_backup_root=resolve_identity_state_backup_root(),
            control_database=resolve_control_plane_path(),
            active_pointer=resolve_active_snapshot_pointer(),
            release_registry_root=resolve_serving_release_registry_path(),
        )
        build = build_initial_snapshot(
            profile=profile, source_package=source_package, snapshot_id=snapshot_id, paths=paths,
        )
        try:
            write_runtime_owner_marker(
                workspace,
                operation_id=operation_id,
                owner_id=operation_id,
                predecessor_snapshot_id=None,
                state="active",
                successor_snapshot_id=snapshot_id,
            )
        except Exception:
            pass
        publication = publish_initial_snapshot(
            build_result=build,
            paths=paths,
            committed_at_utc=_now(),
            publication_operation_id=f"initial_publication:{operation_id}",
        )
        try:
            write_runtime_owner_marker(
                workspace,
                operation_id=operation_id,
                owner_id=operation_id,
                predecessor_snapshot_id=None,
                state="completed",
                successor_snapshot_id=snapshot_id,
                checkpoint_verified=True,
            )
        except Exception:
            pass
        result = {
            "status": "success", "operation_id": operation_id,
            "snapshot_id": snapshot_id, "manifest_sha256": build["manifest_sha256"],
            "database_generation_id": build["database_generation_id"],
            "release_id": publication["release"]["release_id"],
            "release_hash": publication["release"]["release_content_hash"],
            "population_count": build["population_count"], "fact_count": build["fact_count"],
            "gap_count": len(source_package.get("gaps") or []),
            "source_receipt_count": len(source_package.get("acquisition_receipts") or []),
            "initial_publication": bool(publication["transition"].get("initial_publication")),
        }
        try:
            record_operation_result(operation_id, result, operation_type="first_install", scope="installation")
        except Exception:
            pass
        return result
    except Exception as exc:
        try:
            write_runtime_owner_marker(
                workspace,
                operation_id=operation_id,
                owner_id=operation_id,
                predecessor_snapshot_id=None,
                state="failed",
            )
        except Exception:
            pass
        try:
            identity_gap = isinstance(exc, HKEXIdentityReferenceGap)
            record_operation_result(operation_id, {
                "status": "failed", "error_type": type(exc).__name__, "error": str(exc),
                "error_code": "identity_reference_gap" if identity_gap else "first_install_failed",
                "error_class": "identity_reference_gap" if identity_gap else "provider_or_update_failed",
            }, operation_type="first_install", scope="installation")
        except Exception:
            pass
        raise
    finally:
        writer_lease.release(status="released")
