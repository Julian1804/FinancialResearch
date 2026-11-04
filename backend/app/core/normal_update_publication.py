"""Bounded publication coordinator for a validated incremental update.

Universe update owners create immutable successor snapshots and advance their
validated heads.  This module is the small application boundary that binds a
successor snapshot to the unchanged component(s), registers the dependency
closure, and advances the active composite release exactly once.
"""

from __future__ import annotations

import json
import inspect
from pathlib import Path
from typing import Any, Mapping

from backend.app.core.artifact_io import sha256_file, utc_now, write_json_atomic
from backend.app.core.governed_components import (
    LEGACY_COMPONENTS, load_governed_components,
    release_component_authority, select_component_snapshots,
)
from backend.app.core.china_public_fund_query import CONTROL_RELATIVE, FUND_QUERY_CONTRACT
from backend.app.core.china_public_fund_update import (
    FundUpdateConfig,
    PublicFundSourceClient,
    run_user_triggered_fund_update,
)
from backend.app.core.retained_consumer import SERVING_BINDING_SCHEMA, register_retained_consumer
from backend.app.core.serving_publication import bytes_sha256, transition_active_release
from backend.app.core.serving_release import (
    RELEASE_SCHEMA_V2,
    contract_content_hash,
    fund_release_contract_from_snapshot,
    release_content_hash,
    verify_release_descriptor,
)
from backend.app.core.storage_profile import (
    resolve_active_snapshot_pointer,
    resolve_control_plane_path,
    resolve_serving_release_registry_path,
    resolve_unpublished_snapshot_path,
)
from backend.app.core.writer_runtime_ownership import InstallationWriterLease, WriterBusyError, acquire_writer_lease, write_runtime_owner_marker
from backend.app.core.runtime_artifact_lifecycle import (
    active_component_snapshot_id,
    post_publication_disposal_contract,
    sweep_runtime_root,
    terminal_disposal_contract,
)


EQUITY_COMPONENT = "CN_A_SHARE"
FUND_COMPONENT = "CN_PUBLIC_FUND"
EQUITY_CONTRACT_ID = "china_equity_minimum_daily_query_v1"
FUND_CONTRACT_ID = "china_public_fund_minimum_query_v1"
MANIFEST_RELATIVE = "metadata/corrected_candidate_manifest_v1.json"


class NormalUpdatePublicationError(RuntimeError):
    pass


def run_fund_update_and_publish(
    config: FundUpdateConfig,
    *,
    repository: Any | None = None,
    source_client: PublicFundSourceClient | None = None,
    run_id: str | None = None,
    update_runner: Any = run_user_triggered_fund_update,
) -> dict[str, Any]:
    """Own one ordinary Fund Update Data action from update through publish.

    The update owner still creates and validates the immutable successor.  A
    material validated result is immediately handed to the accepted release
    coordinator before this function returns.  No-material-change results do
    not enter the publication path.
    """
    operation_id = run_id or "fund_update_workflow"
    try:
        writer_lease = acquire_writer_lease(
            operation_id=operation_id,
            database_path=getattr(config, "writer_control_path", None),
        )
    except WriterBusyError as exc:
        return {
            "schema_version": "fr_fund_update_publication_result_v1",
            "run_id": run_id,
            "result": "busy",
            "head_advanced": False,
            "error": "installation_writer_busy",
            "error_class": "conflict_or_busy",
            "writer_owner_id": exc.record.owner_id,
            "writer_operation_id": exc.record.operation_id,
        }
    try:
        # Cleanup shares the installation writer lease with update/publish so
        # two processes cannot race over the same terminal run root.
        sweep_runtime_root(
            config.output_root,
            active_snapshot_id=active_component_snapshot_id(FUND_COMPONENT),
            perform=True,
        )
        result = _run_fund_update_and_publish_owned(
            config,
            repository=repository,
            source_client=source_client,
            run_id=run_id,
            update_runner=update_runner,
            writer_lease=writer_lease,
        )
        if writer_lease.record:
            result["writer_ownership"] = {
                "owner_id": writer_lease.record.owner_id,
                "operation_id": writer_lease.record.operation_id,
                "pid": writer_lease.record.pid,
                "scope": "update_validate_publish",
            }
            run_root = config.output_root / "runs" / str(result.get("run_id") or run_id or "")
            if run_root.is_dir():
                write_runtime_owner_marker(
                    run_root,
                    operation_id=writer_lease.record.operation_id,
                    owner_id=writer_lease.record.owner_id,
                    predecessor_snapshot_id=result.get("predecessor_snapshot_id"),
                    state="completed",
                    successor_snapshot_id=result.get("successor_snapshot_id"),
                    checkpoint_verified=bool(result.get("successor_snapshot_id")),
                    recovery_contract=(
                        terminal_disposal_contract()
                        if not result.get("successor_snapshot_id")
                        and result.get("result") == "no_material_change"
                        else post_publication_disposal_contract()
                        if result.get("successor_snapshot_id")
                        and result.get("publication", {}).get("status") in {"published", "already_active", "committed"}
                        else None
                    ),
                )
        return result
    except Exception:
        if writer_lease.record:
            run_root = config.output_root / "runs" / str(run_id or "")
            if run_root.is_dir():
                try:
                    write_runtime_owner_marker(
                        run_root,
                        operation_id=writer_lease.record.operation_id,
                        owner_id=writer_lease.record.owner_id,
                        predecessor_snapshot_id=None,
                        state="failed",
                    )
                except Exception:
                    pass
        writer_lease.release(status="failed")
        raise
    finally:
        if writer_lease.record and writer_lease.record.status == "active":
            writer_lease.release()


def _run_fund_update_and_publish_owned(
    config: FundUpdateConfig,
    *,
    repository: Any | None,
    source_client: PublicFundSourceClient | None,
    run_id: str | None,
    update_runner: Any,
    writer_lease: InstallationWriterLease,
) -> dict[str, Any]:
    update_kwargs = {
        "repository": repository,
        "source_client": source_client,
        "run_id": run_id,
    }
    try:
        parameters = inspect.signature(update_runner).parameters
        if "writer_lease" in parameters or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        ):
            update_kwargs["writer_lease"] = writer_lease
    except (TypeError, ValueError):
        # Callable objects without an inspectable signature remain compatible
        # with the historical update-runner contract.
        pass
    result = dict(update_runner(config, **update_kwargs))
    result_name = str(result.get("result") or "")
    if result_name == "no_material_change":
        result["active_pointer_changed"] = False
        result["active_pointer_unchanged"] = True
        result["active_pointer_status"] = "unchanged"
        result["publication"] = {
            "status": "not_attempted",
            "reason": "no_material_change",
            "pointer_changed": False,
        }
        return result
    if result_name == "success" and result.get("head_advanced") and result.get("successor_snapshot_id"):
        # The updater's flag describes its pre-publication phase.  Preserve it
        # under an explicit stage key and make the workflow-level flag describe
        # the final Active Snapshot state returned to the product caller.
        if "active_pointer_unchanged" in result:
            result["update_stage_active_pointer_unchanged"] = result.pop("active_pointer_unchanged")
        publication = publish_validated_successor(
            successor_snapshot_id=str(result["successor_snapshot_id"]),
            operation_id=f"normal_update_publication:{run_id or result.get('run_id') or result['successor_snapshot_id']}",
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
        return result
    if result_name in {"success_with_source_gaps", "incomplete_source_refresh", "untrustworthy_authoritative_refresh"}:
        result["publication"] = {
            "status": "not_attempted",
            "reason": "validated_update_not_complete",
            "pointer_changed": False,
        }
    return result


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest(snapshot_id: str) -> tuple[Path, dict[str, Any], str]:
    root = resolve_unpublished_snapshot_path(snapshot_id)
    path = root / MANIFEST_RELATIVE
    if not path.is_file():
        raise NormalUpdatePublicationError(f"snapshot manifest is unavailable: {snapshot_id}")
    return root, _load(path), sha256_file(path)


def _integration_proof(component_snapshot: str, served: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    _root, component, _hash = _manifest(component_snapshot)
    members = {row["relative_path"]: row for row in component["files"]}
    changed = sorted(
        path for path in set(members) & set(served)
        if (members[path].get("row_count"), members[path].get("byte_count"), members[path].get("content_sha256"))
        != (served[path].get("row_count"), served[path].get("byte_count"), served[path].get("content_sha256"))
    )
    missing = sorted(set(members) - set(served))
    if missing:
        raise NormalUpdatePublicationError(
            f"successor snapshot dropped component members: {component_snapshot}: {missing[:3]}"
        )
    return {
        "component_member_count": len(members),
        "identical_member_count": len(members) - len(changed),
        "merged_shared_owner_paths": changed,
    }


def publish_validated_successor(
    *,
    successor_snapshot_id: str,
    predecessor_release: Mapping[str, Any] | None = None,
    changed_component: str = FUND_COMPONENT,
    operation_id: str | None = None,
    committed_at_utc: str | None = None,
    component_snapshots: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Publish one validated successor while preserving the other component.

    The validated successor is expected to be a hard-link/inherited snapshot of
    the active snapshot.  Component proofs are calculated from physical
    manifests; no business classification is imported into the validator.
    """
    registry, registry_sha256 = load_governed_components()
    if changed_component not in registry:
        raise ValueError("unregistered changed component")
    pointer = resolve_active_snapshot_pointer()
    active = dict(predecessor_release) if predecessor_release is not None else _load(pointer)
    if active.get("release_type") != "composite_serving_release":
        raise NormalUpdatePublicationError("active release is not a composite serving release")
    successor_root, successor_manifest, successor_hash = _manifest(successor_snapshot_id)
    if successor_manifest.get("publication_state") == "unpublished_governed_recovery_candidate":
        raise NormalUpdatePublicationError(
            "governed recovery candidate has no validated serving publication contract"
        )
    if changed_component == EQUITY_COMPONENT:
        from backend.app.core.subject_graph_projection import verify_subject_graph_completion
        verify_subject_graph_completion(successor_root)
    served = {row["relative_path"]: row for row in successor_manifest["files"]}
    generation = str(successor_manifest.get("database_generation_id") or active.get("database_generation_id") or "")
    if generation != str(active.get("database_generation_id") or ""):
        raise NormalUpdatePublicationError("successor mixes database generations")
    old_components = {str(row["component_id"]): dict(row) for row in active.get("component_bindings", [])}
    overrides = dict(component_snapshots or {})
    if overrides.get(changed_component, successor_snapshot_id) != successor_snapshot_id:
        raise NormalUpdatePublicationError("changed component must bind the validated successor")
    try:
        selected = select_component_snapshots(
            list(old_components.values()), {**overrides, changed_component: successor_snapshot_id},
            registry=registry,
        )
    except ValueError as exc:
        raise NormalUpdatePublicationError(str(exc)) from exc
    from backend.app.core.component_snapshot_integration import publication_union_if_needed
    needs_union = False
    for key, sid in selected.items():
        _, component_manifest, _ = _manifest(sid)
        for row in component_manifest["files"]:
            relative = row["relative_path"]
            if relative not in served or (key == FUND_COMPONENT and relative.startswith("metadata/china_public_fund/")
                    and served[relative]["content_sha256"] != row["content_sha256"]):
                needs_union = True
    if needs_union and set(selected) - LEGACY_COMPONENTS:
        raise NormalUpdatePublicationError(
            "registered-component successor must physically integrate all inherited members before publication"
        )
    served_snapshot_id = (publication_union_if_needed(candidate_snapshot_id=successor_snapshot_id,
        equity_snapshot_id=selected[EQUITY_COMPONENT], fund_snapshot_id=selected[FUND_COMPONENT])
        if needs_union else successor_snapshot_id)
    successor_root, successor_manifest, successor_hash = _manifest(served_snapshot_id)
    served = {row["relative_path"]: row for row in successor_manifest["files"]}
    component_rows = []
    for component_id, component_snapshot in selected.items():
        _root, _component_manifest, component_hash = _manifest(component_snapshot)
        component_rows.append({
            "component_id": component_id,
            "snapshot_id": component_snapshot,
            "manifest_sha256": component_hash,
            "database_generation_id": generation,
            "integration_proof": _integration_proof(component_snapshot, served),
        })
    if changed_component == FUND_COMPONENT or FUND_COMPONENT in overrides:
        fund_contract = fund_release_contract_from_snapshot(
            _load(successor_root / FUND_QUERY_CONTRACT),
            sha256_file(successor_root / FUND_QUERY_CONTRACT),
        )
    else:
        fund_contract = next(row for row in active["serving_contracts"] if row["contract_id"] == FUND_CONTRACT_ID)["contract"]
    old_equity_contract = next(row for row in active["serving_contracts"] if row["contract_id"] == EQUITY_CONTRACT_ID)
    contracts = [
        {
            "contract_id": FUND_CONTRACT_ID,
            "owner": "embedded_release_contract",
            "contract": fund_contract,
            "content_sha256": contract_content_hash(fund_contract),
            "source_snapshot_contract": {
                "relative_path": FUND_QUERY_CONTRACT,
                "content_sha256": sha256_file(successor_root / FUND_QUERY_CONTRACT),
            },
        },
        dict(old_equity_contract),
    ]
    release_id = f"release_{served_snapshot_id}"
    descriptor: dict[str, Any] = {
        "release_type": "composite_serving_release",
        "schema_version": RELEASE_SCHEMA_V2,
        "release_id": release_id,
        "snapshot_id": served_snapshot_id,
        "snapshot_manifest_sha256": successor_hash,
        "database_generation_id": generation,
        "read_model_release_id": None,
        "read_model_manifest_sha256": None,
        "read_model_release_content_hash": None,
        "source_contract_id": successor_manifest.get("source_contract_id"),
        "source_contract_version": successor_manifest.get("source_contract_version"),
        "component_bindings": component_rows,
        "serving_contracts": contracts,
    }
    if set(selected) - LEGACY_COMPONENTS:
        descriptor["component_authority"] = release_component_authority(
            set(selected), registry=registry, registry_sha256=registry_sha256,
        )
    descriptor["release_content_hash"] = release_content_hash(descriptor)
    verify_release_descriptor(descriptor)
    registry = resolve_serving_release_registry_path() / "unpublished" / f"{release_id}.json"
    if registry.exists() and _load(registry) != descriptor:
        raise NormalUpdatePublicationError("release registry identity collision")
    write_json_atomic(registry, descriptor)
    control_member = next(row for row in successor_manifest["files"] if row["relative_path"] == CONTROL_RELATIVE)
    binding = {
        "schema_version": SERVING_BINDING_SCHEMA,
        "release_descriptor": descriptor,
        "database_version_id": served_snapshot_id,
        "manifest_sha256": successor_hash,
        "control_dependency": {
            "owner": "snapshot_member",
            "relative_path": CONTROL_RELATIVE,
            "content_sha256": control_member["content_sha256"],
            "byte_count": control_member["byte_count"],
        },
        "read_model_dependency": None,
    }
    consumer_id, closure = register_retained_consumer(
        resolve_control_plane_path(), binding, consumer_type="serving_release",
        snapshot_root=resolve_unpublished_snapshot_path,
        control_relative_path=CONTROL_RELATIVE, required_member_paths=[],
    )
    prior_bytes = pointer.read_bytes() if pointer.is_file() else b""
    transition = transition_active_release(
        active_pointer=pointer,
        control_database=resolve_control_plane_path(),
        target_release=descriptor,
        target_retention_consumer_id=consumer_id,
        expected_active_sha256=bytes_sha256(prior_bytes),
        operation_id=operation_id or f"normal_update_publication:{release_id}",
        operation_type="publication",
        committed_at_utc=committed_at_utc or utc_now(),
        snapshot_root=resolve_unpublished_snapshot_path,
    )
    return {
        "result": "published" if transition.get("pointer_changed") else "already_active",
        "release": descriptor,
        "retention_consumer_id": consumer_id,
        "retention_closure": closure,
        "transition": transition,
        "predecessor_release_id": active.get("release_id"),
        "predecessor_release_hash": active.get("release_content_hash"),
        "successor_snapshot_id": successor_snapshot_id,
        "changed_component": changed_component,
    }
