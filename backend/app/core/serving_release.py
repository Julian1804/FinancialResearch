"""Immutable serving-release binding and component-provenance verification."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from backend.app.core.artifact_io import canonical_json, sha256_file
from backend.app.core.storage_profile import (
    resolve_active_snapshot_pointer,
    resolve_read_model_release_path,
    resolve_serving_release_registry_path,
    resolve_unpublished_snapshot_path,
)


RELEASE_SCHEMA_V2 = "fr_composite_serving_release_v2"
FUND_CONTRACT_ID = "china_public_fund_minimum_query_v1"
PINNED_FUND_BINDING = "request_pinned_immutable_serving_release"
LEGACY_FUND_BINDING = "resolve the current immutable validated CN_PUBLIC_FUND head for each request"


class ServingReleaseError(RuntimeError):
    pass


class ActiveReleaseAbsent(ServingReleaseError):
    code = "active_release_unavailable"
    status_code = 503


def release_content_hash(payload: Mapping[str, Any]) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "release_content_hash"}
    return hashlib.sha256(canonical_json(unsigned).encode("utf-8")).hexdigest()


def contract_content_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(payload)).encode("utf-8")).hexdigest()


def fund_release_contract_from_snapshot(
    snapshot_contract: Mapping[str, Any], source_sha256: str,
) -> dict[str, Any]:
    """Apply the accepted V1 release-level binding to an immutable Fund member.

    The old snapshot text remains provenance; it must never direct a serving
    request to follow the mutable validated head. Unknown bindings fail closed.
    """
    source = dict(snapshot_contract)
    binding = source.get("release_binding")
    if binding == PINNED_FUND_BINDING:
        return source
    if binding != LEGACY_FUND_BINDING:
        raise ServingReleaseError("Fund snapshot has an unsupported release-binding contract")
    return {
        **source,
        "schema_version": "fr_china_public_fund_release_pinned_query_contract_v1",
        "release_binding": PINNED_FUND_BINDING,
        "alias_resolution_date_parameter": "alias_effective_date",
        "alias_resolution_date_semantics": "lifecycle-effective date used only to select an effective scoped alias",
        "excluded_alias_resolution_time_semantics": [
            "knowledge_cutoff", "publication_time", "revision_time",
            "source_availability_time", "physical_representation_time",
        ],
        "snapshot_contract_binding": {
            "relative_path": "metadata/china_public_fund/query_contract_v1.json",
            "content_sha256": source_sha256,
            "superseded_field": "release_binding",
            "superseded_value": LEGACY_FUND_BINDING,
        },
    }


@dataclass(frozen=True)
class PinnedServingRelease:
    release_type: str
    snapshot_id: str | None
    read_model_release_id: str | None
    release_hash: str
    read_model_release_hash: str | None
    release_id: str | None = None
    database_generation_id: str | None = None
    component_bindings: tuple[dict[str, Any], ...] = ()
    serving_contracts: tuple[dict[str, Any], ...] = ()

    def component(self, component_id: str) -> dict[str, Any]:
        matches = [row for row in self.component_bindings if row.get("component_id") == component_id]
        if len(matches) != 1:
            raise ServingReleaseError(f"serving release has no unique component: {component_id}")
        return dict(matches[0])

    def contract(self, contract_id: str) -> dict[str, Any]:
        matches = [row for row in self.serving_contracts if row.get("contract_id") == contract_id]
        if len(matches) != 1:
            raise ServingReleaseError(f"serving release has no unique contract: {contract_id}")
        return dict(matches[0])


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest_index(value: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for stored in value.get("files", []):
        row = dict(stored)
        relative = str(row.get("relative_path") or "")
        if not relative or relative in result:
            raise ServingReleaseError("snapshot manifest contains a missing or duplicate member path")
        result[relative] = row
    return result


def _signature(row: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    return row.get("row_count"), row.get("byte_count"), row.get("content_sha256")


def verify_release_descriptor(
    payload: Mapping[str, Any],
    *,
    snapshot_root: Callable[[str], Path] = resolve_unpublished_snapshot_path,
    read_model_root: Callable[[str], Path] = resolve_read_model_release_path,
) -> dict[str, Any]:
    """Verify release identity, physical snapshot binding and component provenance.

    Immutable business members are not re-hashed. Their accepted path/size/hash
    signatures are compared through the component and integrated manifests.
    Small manifests and query-contract members are hashed directly.
    """
    value = dict(payload)
    if value.get("release_type") != "composite_serving_release":
        raise ServingReleaseError("unsupported serving release type")
    if value.get("schema_version") != RELEASE_SCHEMA_V2:
        raise ServingReleaseError("component verification requires the V2 serving release schema")
    if value.get("release_content_hash") != release_content_hash(value):
        raise ServingReleaseError("serving release content hash mismatch")
    snapshot_id = str(value.get("snapshot_id") or "")
    if not snapshot_id:
        raise ServingReleaseError("serving release has no snapshot")
    root = snapshot_root(snapshot_id)
    manifest_path = root / "metadata/corrected_candidate_manifest_v1.json"
    if not manifest_path.is_file():
        raise ServingReleaseError("served snapshot manifest is unavailable")
    actual_manifest_hash = sha256_file(manifest_path)
    if actual_manifest_hash != value.get("snapshot_manifest_sha256"):
        raise ServingReleaseError("served snapshot manifest hash mismatch")
    manifest = _load_json(manifest_path)
    if manifest.get("snapshot_id") != snapshot_id:
        raise ServingReleaseError("served snapshot identity mismatch")
    if manifest.get("publication_state") == "unpublished_governed_recovery_candidate":
        raise ServingReleaseError("unpublished governed recovery candidate cannot serve")
    served_members = _manifest_index(manifest)
    # New completed releases carry a small, hash-bound semantic proof. Legacy
    # descriptors remain readable for exact historical bindings and rollback.
    from backend.app.core.subject_graph_projection import COMPLETION, SubjectGraphCompletionError, verify_subject_graph_completion
    if COMPLETION in served_members:
        try:
            verify_subject_graph_completion(root, deep=False)
        except SubjectGraphCompletionError as exc:
            raise ServingReleaseError(str(exc)) from exc

    components = [dict(row) for row in value.get("component_bindings", [])]
    if not components or len({row.get("component_id") for row in components}) != len(components):
        raise ServingReleaseError("serving release component bindings are missing or duplicated")
    from backend.app.core.governed_components import validate_embedded_component_authority
    try:
        validate_embedded_component_authority(
            {str(row["component_id"]) for row in components}, value.get("component_authority"),
        )
    except (KeyError, ValueError) as exc:
        raise ServingReleaseError(str(exc)) from exc
    generation = str(value.get("database_generation_id") or "")
    if not generation or any(row.get("database_generation_id") != generation for row in components):
        raise ServingReleaseError("serving release mixes database generations")
    component_results = []
    for component in components:
        component_snapshot = str(component.get("snapshot_id") or "")
        component_manifest_path = snapshot_root(component_snapshot) / "metadata/corrected_candidate_manifest_v1.json"
        if not component_manifest_path.is_file():
            raise ServingReleaseError("component manifest is unavailable")
        component_hash = sha256_file(component_manifest_path)
        if component_hash != component.get("manifest_sha256"):
            raise ServingReleaseError("component manifest hash mismatch")
        component_manifest = _load_json(component_manifest_path)
        if component_manifest.get("snapshot_id") != component_snapshot:
            raise ServingReleaseError("component snapshot identity mismatch")
        component_members = _manifest_index(component_manifest)
        missing = sorted(set(component_members) - set(served_members))
        changed = sorted(
            path for path in set(component_members) & set(served_members)
            if _signature(component_members[path]) != _signature(served_members[path])
        )
        proof = dict(component.get("integration_proof") or {})
        allowed_changed = sorted(proof.get("merged_shared_owner_paths", []))
        if missing or changed != allowed_changed:
            raise ServingReleaseError("component members do not match the declared integration proof")
        if proof.get("component_member_count") != len(component_members):
            raise ServingReleaseError("component member-count proof mismatch")
        if proof.get("identical_member_count") != len(component_members) - len(changed):
            raise ServingReleaseError("component identical-member proof mismatch")
        component_results.append({
            "component_id": component["component_id"],
            "snapshot_id": component_snapshot,
            "manifest_sha256": component_hash,
            "component_member_count": len(component_members),
            "identical_member_count": len(component_members) - len(changed),
            "merged_shared_owner_paths": changed,
            "missing_member_count": len(missing),
        })

    contracts = [dict(row) for row in value.get("serving_contracts", [])]
    if not contracts or len({row.get("contract_id") for row in contracts}) != len(contracts):
        raise ServingReleaseError("serving contracts are missing or duplicated")
    contract_results = []
    for contract in contracts:
        contract_id = str(contract.get("contract_id") or "")
        owner = contract.get("owner")
        if owner == "snapshot_member":
            if contract_id == FUND_CONTRACT_ID:
                raise ServingReleaseError("Fund release contract must be embedded in the serving release")
            relative = str(contract.get("relative_path") or "")
            member = served_members.get(relative)
            if member is None or member.get("content_sha256") != contract.get("content_sha256"):
                raise ServingReleaseError(f"snapshot query contract is not manifest-bound: {contract_id}")
            physical = root / relative
            if not physical.is_file() or physical.stat().st_size != int(member.get("byte_count") or -1):
                raise ServingReleaseError(f"snapshot query contract is unavailable: {contract_id}")
            if sha256_file(physical) != contract.get("content_sha256"):
                raise ServingReleaseError(f"snapshot query contract hash mismatch: {contract_id}")
        elif owner == "embedded_release_contract":
            embedded = contract.get("contract")
            if not isinstance(embedded, dict) or contract_content_hash(embedded) != contract.get("content_sha256"):
                raise ServingReleaseError(f"embedded query contract hash mismatch: {contract_id}")
            source = contract.get("source_snapshot_contract")
            if source is not None:
                source = dict(source)
                relative = str(source.get("relative_path") or "")
                member = served_members.get(relative)
                if member is None or member.get("content_sha256") != source.get("content_sha256"):
                    raise ServingReleaseError(f"embedded contract source is not manifest-bound: {contract_id}")
                if contract_id == FUND_CONTRACT_ID:
                    physical = root / relative
                    if not physical.is_file() or sha256_file(physical) != source["content_sha256"]:
                        raise ServingReleaseError("Fund contract source is unavailable or changed")
                    expected = fund_release_contract_from_snapshot(
                        _load_json(physical), str(source["content_sha256"]),
                    )
                    if embedded != expected:
                        raise ServingReleaseError("Fund release contract is not query-compatible with its snapshot")
            if contract_id == FUND_CONTRACT_ID and (
                source is None or embedded.get("release_binding") != PINNED_FUND_BINDING
            ):
                raise ServingReleaseError("Fund release contract is not request-pinned")
        else:
            raise ServingReleaseError(f"unsupported query-contract owner: {contract_id}")
        contract_results.append({"contract_id": contract_id, "owner": owner, "content_sha256": contract["content_sha256"]})

    read_model_result: dict[str, Any] | None = None
    read_model_id = value.get("read_model_release_id")
    if read_model_id:
        read_model_manifest_path = read_model_root(str(read_model_id)) / "read_model_release_manifest_v1.json"
        if not read_model_manifest_path.is_file():
            raise ServingReleaseError("read-model release manifest is unavailable")
        digest = sha256_file(read_model_manifest_path)
        read_model_manifest = _load_json(read_model_manifest_path)
        if digest != value.get("read_model_manifest_sha256") or read_model_manifest.get("release_content_hash") != value.get("read_model_release_content_hash"):
            raise ServingReleaseError("read-model release binding mismatch")
        read_model_result = {"read_model_release_id": read_model_id, "manifest_sha256": digest}

    return {
        "release_id": value.get("release_id"),
        "release_content_hash": value["release_content_hash"],
        "snapshot_id": snapshot_id,
        "snapshot_manifest_sha256": actual_manifest_hash,
        "database_generation_id": generation,
        "components": component_results,
        "contracts": contract_results,
        "read_model": read_model_result,
        "business_payload_rows_read": 0,
        "large_immutable_file_hash_reads": 0,
    }


def pin_serving_release(pointer_path: Path | None = None) -> PinnedServingRelease:
    pointer = pointer_path or resolve_active_snapshot_pointer()
    if not pointer.is_file():
        raise ActiveReleaseAbsent("active serving release pointer is unavailable")
    payload = _load_json(pointer)
    release_type = str(payload.get("release_type", ""))
    if release_type == "legacy_sqlite_compatibility":
        return PinnedServingRelease(
            release_type=release_type,
            snapshot_id=None,
            read_model_release_id=None,
            release_hash=str(payload["content_hash"]),
            read_model_release_hash=None,
        )
    if release_type != "composite_serving_release":
        raise ServingReleaseError("unsupported serving release type")
    if payload.get("schema_version") == RELEASE_SCHEMA_V2:
        verify_release_descriptor(payload)
    return PinnedServingRelease(
        release_type=release_type,
        snapshot_id=str(payload["snapshot_id"]),
        read_model_release_id=(str(payload["read_model_release_id"]) if payload.get("read_model_release_id") else None),
        release_hash=str(payload["release_content_hash"]),
        read_model_release_hash=(str(payload["read_model_release_content_hash"]) if payload.get("read_model_release_content_hash") else None),
        release_id=(str(payload["release_id"]) if payload.get("release_id") else None),
        database_generation_id=(str(payload["database_generation_id"]) if payload.get("database_generation_id") else None),
        component_bindings=tuple(dict(row) for row in payload.get("component_bindings", [])),
        serving_contracts=tuple(dict(row) for row in payload.get("serving_contracts", [])),
    )


def pin_registered_serving_release(
    release_id: str,
    release_hash: str,
    *,
    registry_root: Path | None = None,
) -> PinnedServingRelease:
    """Resolve one immutable, explicitly identified serving release.

    This is the continuation token used by sessions that must not follow a
    later active-pointer transition.  Registry membership identifies the
    descriptor; its content hash and normal release verification remain
    mandatory.
    """
    if not release_id or any(token in release_id for token in ("/", "\\", "..")):
        raise ServingReleaseError("release_id must be one path-safe segment")
    if not release_hash:
        raise ServingReleaseError("release_hash is required for an immutable release binding")
    root = registry_root or (resolve_serving_release_registry_path() / "unpublished")
    descriptor = root / f"{release_id}.json"
    if not descriptor.is_file():
        raise ServingReleaseError("registered serving release is unavailable")
    pinned = pin_serving_release(descriptor)
    if pinned.release_id != release_id or pinned.release_hash != release_hash:
        raise ServingReleaseError("registered serving release identity or hash mismatch")
    return pinned
