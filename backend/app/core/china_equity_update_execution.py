"""Production execution owner for the supported China-region Equity update."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from backend.app.core.china_equity_materialization import run_discovery_plan
from backend.app.core.china_equity_update_chain import (
    ValidatedChinaEquityUpdateRepository,
    run_continuous_user_update,
)
from backend.app.core.china_equity_update_workflow import UserUpdateConfig, config_from_environment
from backend.app.core.storage_profile import resolve_identity_state_backup_root, resolve_identity_state_path
from backend.app.core.subject_identity import InstallationIdentityState
from backend.app.core.validated_update_repository import ValidatedUpdateRepository, validate_head_files
from backend.app.core.writer_runtime_ownership import InstallationWriterLease, write_runtime_owner_marker
from backend.app.core.runtime_artifact_lifecycle import terminal_disposal_contract


Materializer = Callable[[Path, Path], dict[str, Any]]


@dataclass(frozen=True)
class ChinaEquityUpdateExecutionError(RuntimeError):
    operation_id: str
    cause_type: str
    cause_message: str
    failure_readback: dict[str, Any]
    failure_evidence_path: str | None

    def __str__(self) -> str:
        return self.cause_message


def execute_china_equity_update(
    operation_id: str,
    *,
    project_root: Path,
    repository: ValidatedUpdateRepository | None = None,
    config: UserUpdateConfig | None = None,
    identity_state: Any | None = None,
    materialize: Materializer | None = None,
    inject_failure_after: str | None = None,
    writer_lease: InstallationWriterLease | None = None,
) -> dict[str, Any]:
    """Execute against the current validated head; no seed/history is selected."""
    if not operation_id or any(token in operation_id for token in ("/", "\\", "..")):
        raise ValueError("operation_id must be one path-safe segment")
    base_config = config or config_from_environment(project_root)
    if base_config.selected_data_families is None:
        from backend.app.core.desired_data_profile import DesiredDataProfileRepository
        from backend.app.core.storage_profile import resolve_control_plane_path
        configuration = DesiredDataProfileRepository(resolve_control_plane_path()).current_configuration()
        scopes = [row for row in configuration.get("scopes", [])
                  if row.get("component_id") == "CN_A_SHARE" and row.get("state") == "enabled"]
        if scopes:
            base_config = replace(base_config, selected_data_families=tuple(sorted({
                family for row in scopes for family in row["data_families"]
            })))
    selected_repository = repository
    head = None
    try:
        # The application entry owns China-region Equity. Use the facade so
        # the lower update chain receives its persisted compatibility component
        # instead of relying on a caller-specific repository subtype.
        selected_repository = selected_repository or ValidatedChinaEquityUpdateRepository()
        head = selected_repository.current("CN_A_SHARE")
        if head is None:
            raise RuntimeError("validated China Equity update head is not initialized")
        validate_head_files(head)
        identity_state = identity_state or InstallationIdentityState(
            resolve_identity_state_path(),
            resolve_identity_state_backup_root(),
        )
        selected_failpoint = inject_failure_after or os.environ.get("FR_A_SHARE_UPDATE_INJECT_FAILURE_AFTER")
        selected_materializer = materialize or (
            lambda plan, output: run_discovery_plan(
                plan,
                output,
                inject_failure_after=selected_failpoint,
            )
        )
        run_root = base_config.output_root / "runs" / operation_id
        result = run_continuous_user_update(
            repository=selected_repository,
            base_config=base_config,
            accepted_owner_path=Path(head.reality_owner_path),
            identity_state=identity_state,
            materialize=selected_materializer,
            run_id=operation_id,
        )
        if writer_lease and writer_lease.record:
            write_runtime_owner_marker(
                run_root,
                operation_id=writer_lease.record.operation_id,
                owner_id=writer_lease.record.owner_id,
                predecessor_snapshot_id=head.snapshot_id,
                state="active" if not result.get("no_op") else "completed",
                successor_snapshot_id=result.get("successor_snapshot_id"),
                checkpoint_verified=bool(result.get("successor_snapshot_id")),
                recovery_contract=terminal_disposal_contract()
                if result.get("no_op") else None,
            )
        return {
            **result,
            "operation_evidence_path": (base_config.output_root / "runs" / operation_id).as_posix(),
        }
    except Exception as exc:
        if writer_lease and writer_lease.record:
            try:
                run_root = base_config.output_root / "runs" / operation_id
                write_runtime_owner_marker(
                    run_root,
                    operation_id=writer_lease.record.operation_id,
                    owner_id=writer_lease.record.owner_id,
                    predecessor_snapshot_id=head.snapshot_id if head else None,
                    state="failed",
                )
            except Exception:
                pass
        failure_path = base_config.output_root / "runs" / operation_id / "chain_run_failure_v1.json"
        failure = {}
        if failure_path.is_file():
            try:
                value = json.loads(failure_path.read_text(encoding="utf-8"))
                failure = value if isinstance(value, dict) else {}
            except (OSError, json.JSONDecodeError):
                failure = {}
        if not failure:
            current_after_failure = None
            if selected_repository is not None:
                try:
                    current_after_failure = selected_repository.current("CN_A_SHARE")
                except Exception:
                    current_after_failure = None
            failure = {
                "schema_version": "fr_a_share_application_update_failure_v1",
                "run_id": operation_id,
                "predecessor_snapshot_id": head.snapshot_id if head else None,
                "head_after_failure": current_after_failure.snapshot_id if current_after_failure else None,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "result": "FAIL",
            }
        raise ChinaEquityUpdateExecutionError(
            operation_id=operation_id,
            cause_type=type(exc).__name__,
            cause_message=str(exc),
            failure_readback=failure,
            failure_evidence_path=failure_path.as_posix() if failure_path.is_file() else None,
        ) from exc


# Public Python compatibility for existing callers and test fixtures.
AShareUpdateExecutionError = ChinaEquityUpdateExecutionError
execute_a_share_update = execute_china_equity_update
