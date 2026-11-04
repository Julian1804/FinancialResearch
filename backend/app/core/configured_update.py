"""One installation-level Update action over current required financial scopes.

The scopes are independently checked, but financial publication remains one
governed Fund/Equity composite transition.  Provider routes do not become
publication components or user-facing Universes.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from backend.app.core.artifact_io import sha256_file, write_json_atomic
from backend.app.core.china_equity_update_execution import (
    ChinaEquityUpdateExecutionError, execute_china_equity_update,
)
from backend.app.core.china_equity_update_workflow import config_from_environment
from backend.app.core.china_public_fund_update import FundUpdateConfig, run_user_triggered_fund_update
from backend.app.core.desired_data_profile import DesiredDataProfileRepository
from backend.app.core.normal_update_publication import publish_validated_successor
from backend.app.core.operation_lifecycle import OperationLifecycleStore, active_serving_view
from backend.app.core.storage_profile import resolve_control_plane_path, resolve_temporary_workspace_path
from backend.app.core.update_scope_contract import freeze_required_update_scopes
from backend.app.core.writer_runtime_ownership import WriterBusyError, acquire_writer_lease


LOCAL_MARKET_SOURCE_FAILURES = frozenset({
    "AcceptedSourceTransportError", "MarketCheckIncomplete", "ConnectionError",
    "ConnectTimeout", "ReadTimeout", "Timeout", "HTTPError", "ProxyError",
})


def _completed_check_receipt(scope_id: str, *, material_change: bool,
                             source_proof: Path, route_warnings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if not source_proof.is_file():
        raise ValueError(f"required check proof is unavailable for {scope_id}")
    checked = datetime.now(timezone.utc)
    return {
        "result": "successful_check", "material_change": material_change,
        "checked_at_utc": checked.isoformat().replace("+00:00", "Z"),
        "check_date": checked.astimezone().date().isoformat(),
        "check_date_basis": "completed_required_scope_checks_in_installation_local_date",
        "source_proof_sha256": sha256_file(source_proof),
        "optional_route_warning_count": len(route_warnings or []),
    }


def _failed_check_receipt(*, reason: str, cause_type: str) -> dict[str, Any]:
    return {
        "result": "failed_check", "material_change": False,
        "checked_at_utc": None, "check_date": None,
        "reason": reason, "cause_type": cause_type,
    }


def run_configured_update(
    *,
    operation_id: str,
    project_root: Path,
    fund_runner: Callable[..., dict[str, Any]] = run_user_triggered_fund_update,
    equity_runner: Callable[..., dict[str, Any]] = execute_china_equity_update,
    publisher: Callable[..., dict[str, Any]] = publish_validated_successor,
    configuration: Mapping[str, Any] | None = None,
    store: OperationLifecycleStore | None = None,
) -> dict[str, Any]:
    """Freeze, check, integrate, then publish once under one writer lease.

    The optional callables are bounded test seams; the ordinary API uses the
    exact production owners above.  No provider work precedes registration or
    denominator freeze.
    """
    if not operation_id or any(part in operation_id for part in ("/", "\\", "..")):
        raise ValueError("operation_id must be one path-safe segment")
    lifecycle = store or OperationLifecycleStore()
    current = dict(configuration) if configuration is not None else DesiredDataProfileRepository(resolve_control_plane_path()).current_configuration()
    denominator = freeze_required_update_scopes(current)
    run_root = resolve_temporary_workspace_path("configured_update") / "runs" / operation_id
    lifecycle.begin(operation_id, operation_type="configured_update", scope="installation", runtime_root=run_root)
    lifecycle.freeze_scope_denominator(operation_id, denominator)
    required_scopes = list(denominator["required_scopes"])
    scope_results: dict[str, dict[str, Any]] = {}
    material_components: dict[str, str] = {}
    prior_active = active_serving_view()
    # One user action observes one calendar cutoff even when market owners run
    # sequentially.  The completion date in each receipt is assigned only
    # after that owner's required checks have actually finished.
    observation_date = date.today().isoformat()
    lease = None

    def mark_unfinished(reason: str, cause_type: str) -> None:
        for scope in required_scopes:
            scope_id = str(scope["scope_id"])
            if scope_id in scope_results:
                continue
            receipt = _failed_check_receipt(reason=reason, cause_type=cause_type)
            scope_results[scope_id] = receipt
            lifecycle.record_scope_result(operation_id, scope_id, receipt)

    try:
        lease = acquire_writer_lease(operation_id=operation_id)
        for scope in required_scopes:
            scope_id = str(scope["scope_id"])
            component = str(scope["component_id"])
            if component == "CN_PUBLIC_FUND":
                fund_run_id = f"{operation_id}_fund"
                fund_root = resolve_temporary_workspace_path("china_public_fund_user_update")
                try:
                    result = fund_runner(
                        FundUpdateConfig(
                            output_root=fund_root, as_of_date=observation_date,
                            selected_data_families=tuple(scope["selected_data_families"]),
                        ),
                        run_id=fund_run_id, writer_lease=lease,
                    )
                except Exception as exc:
                    # Unknown Fund failures may include shared integrity or
                    # identity defects; do not reclassify them as local source
                    # failures simply to obtain a partial publication.
                    raise RuntimeError("Fund update failed before scoped source completion was proved") from exc
                result_name = str(result.get("result") or "")
                proof = fund_root / "runs" / fund_run_id / "discovery_and_acquisition_v1.json"
                proof_value = json.loads(proof.read_text(encoding="utf-8")) if proof.is_file() else {}
                if (result_name in {"success", "no_material_change"}
                        and result.get("refresh_complete") is True
                        and proof_value.get("refresh_complete") is True):
                    changed = result_name == "success" and bool(result.get("head_advanced"))
                    if changed:
                        material_components[component] = str(result["successor_snapshot_id"])
                    receipt = _completed_check_receipt(scope_id, material_change=changed, source_proof=proof)
                else:
                    receipt = _failed_check_receipt(reason="required_fund_source_refresh_incomplete", cause_type=result_name)
                scope_results[scope_id] = receipt
                lifecycle.record_scope_result(operation_id, scope_id, receipt)
                continue

            market_key = str(scope["market_key"])
            equity_run_id = f"{operation_id}_{market_key}"
            config = replace(
                config_from_environment(project_root),
                market_scope=market_key,
                as_of_date=observation_date,
                selected_data_families=tuple(scope["selected_data_families"]),
            )
            try:
                result = equity_runner(
                    equity_run_id, project_root=project_root,
                    config=config, writer_lease=lease,
                )
            except ChinaEquityUpdateExecutionError as exc:
                if exc.cause_type not in LOCAL_MARKET_SOURCE_FAILURES:
                    raise
                receipt = _failed_check_receipt(
                    reason="required_market_source_route_incomplete", cause_type=exc.cause_type,
                )
            else:
                if result.get("result") != "PASS":
                    raise ValueError("Equity market runner returned an unclassified result")
                proof = Path(result["operation_evidence_path"]) / "market_required_check_v1.json"
                market_check = json.loads(proof.read_text(encoding="utf-8"))
                if market_check.get("market_scope") != market_key or market_check.get("required_route_complete") is not True:
                    raise ValueError("Equity market completion proof does not bind this successful scope")
                changed = not bool(result.get("no_op")) and bool(result.get("successor_snapshot_id"))
                if changed:
                    material_components[component] = str(result["successor_snapshot_id"])
                receipt = _completed_check_receipt(
                    scope_id, material_change=changed, source_proof=proof,
                    route_warnings=result.get("source_route_warnings"),
                )
            scope_results[scope_id] = receipt
            lifecycle.record_scope_result(operation_id, scope_id, receipt)

        publication = None
        if material_components:
            changed_component = "CN_A_SHARE" if "CN_A_SHARE" in material_components else "CN_PUBLIC_FUND"
            publication = publisher(
                successor_snapshot_id=material_components[changed_component],
                changed_component=changed_component,
                component_snapshots=material_components,
                operation_id=f"normal_update_publication:{operation_id}",
            )
        failed = [scope_id for scope_id, value in scope_results.items() if value["result"] == "failed_check"]
        active_after = active_serving_view()
        result = {
            "schema_version": "fr_configured_update_result_v1",
            "operation_id": operation_id,
            "status": "success" if publication is not None else ("failed" if failed else "no_material_change"),
            "result": "published_partial" if publication is not None and failed else
                      "published" if publication is not None else
                      "partial_no_material_change" if failed else "no_material_change",
            "partial": bool(failed),
            "denominator_sha256": denominator["denominator_sha256"],
            "required_scope_ids": [scope["scope_id"] for scope in required_scopes],
            "scope_results": scope_results,
            "changed_components": material_components,
            "publication": publication,
            "predecessor_release_id": prior_active.get("release_id"),
            "active_release_id": active_after.get("release_id"),
            "active_release_hash": active_after.get("release_hash"),
            "active_snapshot_id": active_after.get("snapshot_id"),
            "active_pointer_changed": prior_active.get("release_hash") != active_after.get("release_hash"),
        }
        lifecycle.transition(operation_id, result, operation_type="configured_update", scope="installation")
        run_root.mkdir(parents=True, exist_ok=True)
        write_json_atomic(run_root / "result_v1.json", result)
        return result
    except WriterBusyError as exc:
        mark_unfinished("writer_busy_no_check", "WriterBusyError")
        result = {
            "status": "busy", "result": "busy", "operation_id": operation_id,
            "writer_operation_id": exc.record.operation_id,
            "denominator_sha256": denominator["denominator_sha256"],
            "scope_results": scope_results,
        }
        lifecycle.transition(operation_id, result, operation_type="configured_update", scope="installation")
        return result
    except Exception as exc:
        # A committed pointer transition wins over a lost response or a later
        # lifecycle-write failure.  The read model rechecks that truth.
        result = {
            "status": "failed", "result": "failed", "operation_id": operation_id,
            "error_type": type(exc).__name__, "denominator_sha256": denominator["denominator_sha256"],
            "scope_results": scope_results,
        }
        try:
            mark_unfinished("not_executed_after_shared_failure", type(exc).__name__)
            result["scope_results"] = scope_results
            lifecycle.transition(operation_id, result, operation_type="configured_update", scope="installation")
        except Exception:
            pass
        raise
    finally:
        if lease is not None and lease.record and lease.record.status == "active":
            lease.release(status="released")
