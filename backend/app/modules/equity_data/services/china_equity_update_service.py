"""Application owner for the supported China-region Equity Update workflow."""

from __future__ import annotations

import threading
import inspect
from pathlib import Path
from typing import Any, Callable

from backend.app.core.china_equity_foundation import current_foundation_state
from backend.app.core.china_equity_update_execution import (
    ChinaEquityUpdateExecutionError,
    execute_china_equity_update,
)
from backend.app.core.desired_data_profile import DesiredDataProfileRepository
from backend.app.core.diagnostics import ErrorClass, current_request_id, log_event, new_operation_id, operation_context
from backend.app.core.normal_update_publication import publish_validated_successor
from backend.app.core.operation_lifecycle import (
    OperationRegistrationUnavailable,
    record_operation_result,
    record_operation_started,
)
from backend.app.core.writer_runtime_ownership import WriterBusyError, acquire_writer_lease, write_runtime_owner_marker
from backend.app.core.runtime_artifact_lifecycle import (
    active_component_snapshot_id,
    post_publication_disposal_contract,
    sweep_runtime_root,
    terminal_disposal_contract,
)
from backend.app.core.storage_profile import resolve_control_plane_path, resolve_temporary_workspace_path


PROJECT_ROOT = Path(__file__).resolve().parents[5]
COMPATIBILITY_CLI = PROJECT_ROOT / "scripts" / "fr_a_share_user_triggered_update.py"
PRODUCTION_OWNER = PROJECT_ROOT / "backend" / "app" / "core" / "china_equity_update_execution.py"
_CHINA_EQUITY_UPDATE_LOCK = threading.Lock()


def equity_runtime_root() -> Path:
    """Installation-owned disposable work, distinct from the source checkout."""
    return resolve_temporary_workspace_path("china_equity_user_update")


def check_update_state() -> dict[str, Any]:
    result = current_foundation_state()
    result["latest_evidence_path"] = equity_runtime_root().as_posix()
    result["production_owner_path"] = PRODUCTION_OWNER.as_posix()
    result["production_owner_exists"] = PRODUCTION_OWNER.is_file()
    result["compatibility_cli_path"] = COMPATIBILITY_CLI.as_posix()
    result["compatibility_cli_exists"] = COMPATIBILITY_CLI.is_file()
    # Additive role fields above supersede these compatibility response keys.
    result["update_script_path"] = COMPATIBILITY_CLI.as_posix()
    result["update_script_exists"] = COMPATIBILITY_CLI.is_file()
    return result


def run_update_pipeline_action(
    action: str = "check",
    *,
    operation_id: str | None = None,
    executor: Callable[..., dict[str, Any]] = execute_china_equity_update,
    writer_lease: Any | None = None,
) -> dict[str, Any]:
    allowed = {"check", "update_china_equity", "update_a_share"}
    if action not in allowed:
        return {"status": "rejected", "error": "unsupported_update_pipeline_action", "allowed_actions": sorted(allowed)}
    if action == "check":
        return check_update_state()
    run_id = operation_id or new_operation_id("china_equity_update")
    if writer_lease is None:
        try:
            owned_lease = acquire_writer_lease(operation_id=run_id)
        except WriterBusyError as exc:
            return {
                "status": "busy",
                "action": action,
                "returncode": 1,
                "operation_id": run_id,
                "error_class": ErrorClass.CONFLICT_OR_BUSY.value,
                "error": "installation_writer_busy",
                "writer_owner_id": exc.record.owner_id,
                "writer_operation_id": exc.record.operation_id,
            }
        try:
            return run_update_pipeline_action(
                action,
                operation_id=run_id,
                executor=executor,
                writer_lease=owned_lease,
            )
        finally:
            owned_lease.release()
    try:
        executor_kwargs: dict[str, Any] = {"project_root": PROJECT_ROOT}
        if writer_lease is not None:
            try:
                parameters = inspect.signature(executor).parameters
                if "writer_lease" in parameters or any(
                    parameter.kind is inspect.Parameter.VAR_KEYWORD
                    for parameter in parameters.values()
                ):
                    executor_kwargs["writer_lease"] = writer_lease
            except (TypeError, ValueError):
                pass
        update_result = executor(run_id, **executor_kwargs)
    except ChinaEquityUpdateExecutionError as exc:
        return {
            "status": "failed",
            "action": action,
            "returncode": 1,
            "operation_id": run_id,
            "error_class": ErrorClass.PROVIDER_OR_UPDATE_FAILED.value,
            "error_type": exc.cause_type,
            "error": exc.cause_message,
            "stdout_tail": "",
            "stderr_tail": exc.cause_message[-2000:],
            "failure_readback": exc.failure_readback,
            "failure_evidence_path": exc.failure_evidence_path,
            "evidence_path": (
                Path(exc.failure_evidence_path).parent.as_posix()
                if exc.failure_evidence_path else equity_runtime_root().as_posix()
            ),
        }
    return {
        "status": "success" if update_result.get("result") == "PASS" else "failed",
        "action": action,
        "returncode": 0 if update_result.get("result") == "PASS" else 1,
        "operation_id": run_id,
        "stdout_tail": "",
        "stderr_tail": "",
        "evidence_path": str(update_result.get("operation_evidence_path") or equity_runtime_root().as_posix()),
        "update_result": update_result,
    }


def run_bounded_update() -> dict[str, Any]:
    return run_update_pipeline_action("update_china_equity")


def run_incremental_refresh() -> dict[str, Any]:
    return run_update_pipeline_action("update_china_equity")


def run_user_triggered_china_equity_update() -> dict[str, Any]:
    """Application entry for the supported China-region Equity scope."""
    operation_id = new_operation_id("china_equity_update")
    with operation_context(operation_id):
        runtime_root = equity_runtime_root() / "runs" / operation_id
        try:
            record_operation_started(
                operation_id,
                operation_type="china_equity_update",
                scope="Equity",
                runtime_root=runtime_root,
                request_id=current_request_id(),
            )
        except OperationRegistrationUnavailable as exc:
            result = {
                "status": "rejected",
                "result": "operation_registration_unavailable",
                "operation_accepted": False,
                "operation_id": None,
                "attempted_operation_id": operation_id,
                "retryable": True,
                "error_code": "operation_registration_unavailable",
                "error_class": ErrorClass.CONTROL_PLANE_UNAVAILABLE.value,
                "error": "the operation could not be durably registered; no financial work was started",
                "provider_calls": 0,
            }
            log_event(
                "operation_rejected",
                level=30,
                capability="china_equity_update",
                stage="operation_registration",
                error_code="operation_registration_unavailable",
                error_type=type(exc).__name__,
            )
            return result
        if not DesiredDataProfileRepository(resolve_control_plane_path()).is_component_configured("CN_A_SHARE"):
            result = {
                "status": "blocked",
                "result": "blocked",
                "error": "no enabled Equity data scope is configured",
                "error_code": "no_data_scope_configured",
                "error_class": ErrorClass.REQUEST_INVALID.value,
                "operation_id": operation_id,
                "provider_calls": 0,
                "publication": {"status": "not_attempted", "reason": "no_data_scope_configured", "pointer_changed": False},
            }
            try:
                record_operation_result(operation_id, result, operation_type="china_equity_update", scope="Equity")
            except Exception as exc:
                log_event("operation_lifecycle_record_failed", level=30, capability="china_equity_update", stage="operation_blocked", error_type=type(exc).__name__)
            return result
        if not _CHINA_EQUITY_UPDATE_LOCK.acquire(blocking=False):
            log_event(
                "operation_rejected",
                level=30,
                capability="china_equity_update",
                stage="update_lock",
                error_class=ErrorClass.CONFLICT_OR_BUSY.value,
                error_code="china_equity_update_already_running",
            )
            result = {
                "status": "busy",
                "error": "china_equity_update_already_running",
                "error_class": ErrorClass.CONFLICT_OR_BUSY.value,
                "operation_id": operation_id,
            }
            try:
                record_operation_result(operation_id, result, operation_type="china_equity_update", scope="Equity")
            except Exception as exc:
                log_event("operation_lifecycle_record_failed", level=30, capability="china_equity_update", stage="operation_busy", error_type=type(exc).__name__)
            return result
        lease_status = "failed"
        try:
            writer_lease = acquire_writer_lease(operation_id=operation_id)
        except WriterBusyError as exc:
            _CHINA_EQUITY_UPDATE_LOCK.release()
            log_event(
                "operation_rejected",
                level=30,
                capability="china_equity_update",
                stage="writer_lease",
                error_class=ErrorClass.CONFLICT_OR_BUSY.value,
                error_code="installation_writer_busy",
                writer_owner_id=exc.record.owner_id,
                writer_operation_id=exc.record.operation_id,
            )
            result = {
                "status": "busy",
                "error": "installation_writer_busy",
                "error_class": ErrorClass.CONFLICT_OR_BUSY.value,
                "operation_id": operation_id,
                "writer_owner_id": exc.record.owner_id,
                "writer_operation_id": exc.record.operation_id,
            }
            try:
                record_operation_result(operation_id, result, operation_type="china_equity_update", scope="Equity")
            except Exception as record_exc:
                log_event("operation_lifecycle_record_failed", level=30, capability="china_equity_update", stage="writer_lease_busy", error_type=type(record_exc).__name__)
            return result
        try:
            # Cleanup shares the installation writer lease with update/publish
            # so competing processes cannot race over a terminal run root.
            sweep_runtime_root(
                equity_runtime_root(),
                active_snapshot_id=active_component_snapshot_id("CN_A_SHARE"),
                perform=True,
            )
            log_event("operation_started", capability="china_equity_update", stage="update_entry")
            result = run_update_pipeline_action("update_china_equity", operation_id=operation_id, writer_lease=writer_lease)
            if result["status"] == "success":
                update_result = result.get("update_result") or {}
                successor_snapshot_id = update_result.get("successor_snapshot_id")
                if successor_snapshot_id and not update_result.get("no_op"):
                    publication = publish_validated_successor(
                        successor_snapshot_id=str(successor_snapshot_id),
                        changed_component="CN_A_SHARE",
                        operation_id=f"normal_update_publication:{operation_id}",
                    )
                    result["publication"] = publication
                    result["active_snapshot_id"] = publication["release"]["snapshot_id"]
                    result["active_release_id"] = publication["release"]["release_id"]
                    result["active_release_hash"] = publication["release"]["release_content_hash"]
                    pointer_changed = bool(publication.get("transition", {}).get("pointer_changed"))
                    result["active_pointer_changed"] = pointer_changed
                    result["active_pointer_unchanged"] = not pointer_changed
                    result["active_pointer_status"] = "published" if pointer_changed else "already_active"
                    result["update_complete_after_publication"] = True
                else:
                    result["active_pointer_changed"] = False
                    result["active_pointer_unchanged"] = True
                    result["active_pointer_status"] = "unchanged"
                    result["publication"] = {
                        "status": "not_attempted",
                        "reason": "no_material_change",
                        "pointer_changed": False,
                    }
            if writer_lease.record:
                result["writer_ownership"] = {
                    "owner_id": writer_lease.record.owner_id,
                    "operation_id": writer_lease.record.operation_id,
                    "pid": writer_lease.record.pid,
                    "scope": "update_validate_publish",
                }
                update_evidence = result.get("update_result") or {}
                run_root_value = result.get("evidence_path") or update_evidence.get("operation_evidence_path")
                if run_root_value:
                    write_runtime_owner_marker(
                        Path(run_root_value),
                        operation_id=writer_lease.record.operation_id,
                        owner_id=writer_lease.record.owner_id,
                        predecessor_snapshot_id=update_evidence.get("predecessor_snapshot_id"),
                        state="completed",
                        successor_snapshot_id=update_evidence.get("successor_snapshot_id"),
                        checkpoint_verified=bool(update_evidence.get("successor_snapshot_id")),
                        recovery_contract=terminal_disposal_contract()
                        if not update_evidence.get("successor_snapshot_id")
                        and update_evidence.get("no_op")
                        else post_publication_disposal_contract()
                        if update_evidence.get("successor_snapshot_id")
                        and result.get("update_complete_after_publication") else None,
                    )
            evidence = result.get("update_result") or result.get("failure_readback") or {}
            log_event(
                "operation_completed" if result["status"] == "success" else "operation_failed",
                level=20 if result["status"] == "success" else 40,
                capability="china_equity_update",
                stage="validated_update_result" if result["status"] == "success" else "update_execution",
                result=result["status"],
                error_code=result.get("error_type"),
                predecessor_snapshot_id=evidence.get("predecessor_snapshot_id"),
                successor_snapshot_id=(result.get("update_result") or {}).get("successor_snapshot_id"),
            )
            try:
                record_operation_result(operation_id, result, operation_type="china_equity_update", scope="Equity")
            except Exception as exc:
                log_event("operation_lifecycle_record_failed", level=30, capability="china_equity_update", stage="operation_result", error_type=type(exc).__name__)
            lease_status = "released"
            return result
        except Exception as exc:
            try:
                record_operation_result(
                    operation_id,
                    {"status": "failed", "error_type": type(exc).__name__, "error_code": "china_equity_update_internal_failure", "error_class": ErrorClass.INTERNAL_FAILURE.value},
                    operation_type="china_equity_update",
                    scope="Equity",
                )
            except Exception as record_exc:
                log_event("operation_lifecycle_record_failed", level=30, capability="china_equity_update", stage="internal_failure", error_type=type(record_exc).__name__)
            raise
        finally:
            writer_lease.release(status=lease_status)
            _CHINA_EQUITY_UPDATE_LOCK.release()


# Old imports are retained for callers of the former A-share application path.
run_user_triggered_a_share_update = run_user_triggered_china_equity_update
