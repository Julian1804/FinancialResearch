"""Durable retention roots for external consumers of immutable FR snapshots."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from backend.app.core.artifact_io import canonical_json, sha256_file
from backend.app.core.incremental_control import IncrementalControlView
from backend.app.core.research_binding import verify_research_binding
from backend.app.core.serving_release import RELEASE_SCHEMA_V2, release_content_hash, verify_release_descriptor
from backend.app.core.storage_profile import resolve_deployment_root, resolve_read_model_release_path


SCHEMA_VERSION = "fr_retained_external_consumer_v1"
PROTECTED = "protected_by_retained_consumer"
ELIGIBLE = "eligible_for_governed_expiry_subject_to_active_rollback_policy"


class RetainedConsumerError(RuntimeError):
    pass


SERVING_BINDING_SCHEMA = "fr_serving_release_retention_binding_v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_retained_consumer_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS retained_external_consumer(
          consumer_id TEXT PRIMARY KEY,
          schema_version TEXT NOT NULL,
          consumer_type TEXT NOT NULL,
          binding_sha256 TEXT NOT NULL,
          binding_json TEXT NOT NULL,
          snapshot_id TEXT NOT NULL,
          snapshot_manifest_sha256 TEXT NOT NULL,
          control_relative_path TEXT NOT NULL,
          required_member_paths_json TEXT NOT NULL,
          status TEXT NOT NULL,
          registered_at_utc TEXT NOT NULL
        )"""
    )


def retained_consumer_id(consumer_type: str, binding: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json({
        "consumer_type": consumer_type,
        "binding": dict(binding),
    }).encode("utf-8")).hexdigest()
    return f"retained_consumer:{digest}"


def _manifest_members(manifest_path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    members: dict[str, dict[str, Any]] = {}
    for stored in manifest.get("files", []):
        row = dict(stored)
        path = str(row.get("relative_path") or "")
        if not path or path in members:
            raise RetainedConsumerError("snapshot manifest has missing or duplicate member paths")
        members[path] = row
    return manifest, members


def _verify_member(root: Path, member: Mapping[str, Any]) -> dict[str, Any]:
    relative_path = str(member["relative_path"])
    path = root / relative_path
    if not path.is_file():
        raise RetainedConsumerError(f"retained dependency is unavailable: {relative_path}")
    size = path.stat().st_size
    if member.get("byte_count") is not None and int(member["byte_count"]) != size:
        raise RetainedConsumerError(f"retained dependency size mismatch: {relative_path}")
    digest = sha256_file(path)
    if digest != str(member["content_sha256"]):
        raise RetainedConsumerError(f"retained dependency hash mismatch: {relative_path}")
    return {
        "relative_path": relative_path,
        "layer_name": str(member.get("layer_name") or ""),
        "byte_count": size,
        "content_sha256": digest,
    }


def _verify_serving_binding(
    binding: Mapping[str, Any], *, snapshot_root: Callable[[str], Path],
) -> dict[str, Any]:
    if binding.get("schema_version") != SERVING_BINDING_SCHEMA:
        raise RetainedConsumerError("unsupported serving-release retention binding")
    release = binding.get("release_descriptor")
    if not isinstance(release, dict) or release.get("release_type") != "composite_serving_release":
        raise RetainedConsumerError("serving retention binding has no composite release")
    if release_content_hash(release) != release.get("release_content_hash"):
        raise RetainedConsumerError("retained serving release hash mismatch")
    snapshot_id = str(release.get("snapshot_id") or "")
    if binding.get("database_version_id") != snapshot_id:
        raise RetainedConsumerError("retained serving snapshot identity mismatch")
    root = snapshot_root(snapshot_id)
    manifest_path = root / "metadata/corrected_candidate_manifest_v1.json"
    if not manifest_path.is_file() or sha256_file(manifest_path) != binding.get("manifest_sha256"):
        raise RetainedConsumerError("retained serving snapshot manifest mismatch")
    if release.get("schema_version") == RELEASE_SCHEMA_V2:
        verify_release_descriptor(release, snapshot_root=snapshot_root)

    control = dict(binding.get("control_dependency") or {})
    if control.get("owner") == "snapshot_member":
        control_path = root / str(control.get("relative_path") or "")
        manifest, members = _manifest_members(manifest_path)
        member = members.get(str(control.get("relative_path") or ""))
        if member is None or member.get("content_sha256") != control.get("content_sha256"):
            raise RetainedConsumerError("retained serving control is not manifest-bound")
    elif control.get("owner") == "deployment_root":
        control_path = resolve_deployment_root(str(control.get("root_ref") or "")) / str(control.get("relative_path") or "")
    else:
        raise RetainedConsumerError("retained serving control owner is unsupported")
    if not control_path.is_file() or control_path.stat().st_size != int(control.get("byte_count") or -1):
        raise RetainedConsumerError("retained serving control dependency is unavailable")

    read_model_result = None
    read_model = binding.get("read_model_dependency")
    if read_model:
        read_model = dict(read_model)
        release_id = str(read_model.get("release_id") or "")
        manifest_path_rm = resolve_read_model_release_path(release_id) / "read_model_release_manifest_v1.json"
        if not manifest_path_rm.is_file() or sha256_file(manifest_path_rm) != read_model.get("manifest_sha256"):
            raise RetainedConsumerError("retained read-model manifest is unavailable or changed")
        manifest_rm = json.loads(manifest_path_rm.read_text(encoding="utf-8"))
        if manifest_rm.get("release_content_hash") != read_model.get("release_content_hash"):
            raise RetainedConsumerError("retained read-model release content hash mismatch")
        read_model_result = {
            "release_id": release_id,
            "manifest_sha256": read_model["manifest_sha256"],
            "member_count": len(manifest_rm.get("files", [])),
        }
    return {
        "schema_version": "fr_serving_release_dependency_closure_v1",
        "snapshot_id": snapshot_id,
        "snapshot_manifest_sha256": binding["manifest_sha256"],
        "dependency_scope": "complete_snapshot_manifest",
        "protected_snapshot_ids": [snapshot_id],
        "control_dependency": {
            "owner": control["owner"],
            "byte_count": control_path.stat().st_size,
            "content_sha256": control["content_sha256"],
        },
        "read_model_dependency": read_model_result,
        "required_members": [],
        "control_chain": [],
        "control_chain_depth": 0,
        "business_payload_rows_read": 0,
        "large_immutable_file_hash_reads": 0,
    }


def inspect_serving_release_physical_inventory(
    binding: Mapping[str, Any], *, snapshot_root: Callable[[str], Path],
) -> dict[str, Any]:
    """Stat every protected release member without reading immutable payload bytes."""
    closure = _verify_serving_binding(binding, snapshot_root=snapshot_root)
    snapshot_id = str(binding["database_version_id"])
    root = snapshot_root(snapshot_id)
    manifest_path = root / "metadata/corrected_candidate_manifest_v1.json"
    manifest, members = _manifest_members(manifest_path)
    missing = []
    size_mismatch = []
    for relative, member in members.items():
        path = root / relative
        if not path.is_file():
            missing.append(relative)
        elif member.get("byte_count") is not None and path.stat().st_size != int(member["byte_count"]):
            size_mismatch.append(relative)
    read_model_missing = []
    read_model_size_mismatch = []
    read_model = binding.get("read_model_dependency")
    read_model_count = 0
    if read_model:
        read_model = dict(read_model)
        read_root = resolve_read_model_release_path(str(read_model["release_id"]))
        read_manifest = json.loads((read_root / "read_model_release_manifest_v1.json").read_text(encoding="utf-8"))
        for member in read_manifest.get("files", []):
            read_model_count += 1
            relative = str(member["relative_path"])
            path = read_root / relative
            if not path.is_file():
                read_model_missing.append(relative)
            elif member.get("byte_count") is not None and path.stat().st_size != int(member["byte_count"]):
                read_model_size_mismatch.append(relative)
    return {
        **closure,
        "snapshot_member_count": len(members),
        "snapshot_declared_bytes": sum(int(row.get("byte_count") or 0) for row in members.values()),
        "snapshot_missing_count": len(missing),
        "snapshot_size_mismatch_count": len(size_mismatch),
        "read_model_member_count": read_model_count,
        "read_model_missing_count": len(read_model_missing),
        "read_model_size_mismatch_count": len(read_model_size_mismatch),
        "payload_files_opened": 0,
        "payload_bytes_read": 0,
    }


def inspect_dependency_closure(
    binding: Mapping[str, Any],
    *,
    snapshot_root: Callable[[str], Path],
    control_relative_path: str,
    required_member_paths: Sequence[str],
) -> dict[str, Any]:
    """Verify the immutable closure required by research or serving consumers."""
    if binding.get("schema_version") == SERVING_BINDING_SCHEMA:
        return _verify_serving_binding(binding, snapshot_root=snapshot_root)
    verify_research_binding(binding)
    snapshot_id = str(binding["database_version_id"])
    root = snapshot_root(snapshot_id)
    manifest_path = root / "metadata/corrected_candidate_manifest_v1.json"
    if not manifest_path.is_file():
        raise RetainedConsumerError("pinned snapshot manifest is unavailable")
    manifest_sha256 = sha256_file(manifest_path)
    if manifest_sha256 != str(binding["manifest_sha256"]):
        raise RetainedConsumerError("research binding manifest hash mismatch")
    manifest, members = _manifest_members(manifest_path)
    if str(manifest.get("snapshot_id") or "") != snapshot_id:
        raise RetainedConsumerError("research binding snapshot identity mismatch")
    required = tuple(sorted(set(str(value) for value in required_member_paths)))
    if not required:
        raise RetainedConsumerError("retained consumer requires at least one business member")
    verified_members = []
    for relative_path in required:
        member = members.get(relative_path)
        if member is None:
            raise RetainedConsumerError(f"required member is absent from manifest: {relative_path}")
        verified_members.append(_verify_member(root, member))
    view = IncrementalControlView(
        snapshot_id,
        control_path=lambda value: snapshot_root(value) / control_relative_path,
        manifest_path=lambda value: snapshot_root(value) / "metadata/corrected_candidate_manifest_v1.json",
        control_relative_path=control_relative_path,
    )
    controls = [
        {
            "snapshot_id": layer.snapshot_id,
            "manifest_path": str(layer.manifest_path),
            "manifest_sha256": sha256_file(layer.manifest_path),
            "control_path": str(layer.control_path),
            "control_sha256": next(
                str(row["content_sha256"])
                for row in json.loads(layer.manifest_path.read_text(encoding="utf-8"))["files"]
                if row.get("relative_path") == control_relative_path
            ),
            "is_checkpoint": layer.is_checkpoint,
        }
        for layer in view.layers
    ]
    return {
        "schema_version": "fr_retained_dependency_closure_v1",
        "snapshot_id": snapshot_id,
        "snapshot_manifest_sha256": manifest_sha256,
        "control_relative_path": control_relative_path,
        "control_chain_depth": view.depth,
        "control_chain": controls,
        "required_members": verified_members,
        "business_payload_rows_read": 0,
    }


def register_retained_consumer(
    control_database: Path,
    binding: Mapping[str, Any],
    *,
    consumer_type: str,
    snapshot_root: Callable[[str], Path],
    control_relative_path: str,
    required_member_paths: Sequence[str],
    registered_at_utc: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Register an already verified immutable dependency closure as a retention root."""
    closure = inspect_dependency_closure(
        binding,
        snapshot_root=snapshot_root,
        control_relative_path=control_relative_path,
        required_member_paths=required_member_paths,
    )
    binding_json = canonical_json(dict(binding))
    binding_sha256 = hashlib.sha256(binding_json.encode("utf-8")).hexdigest()
    consumer_id = retained_consumer_id(consumer_type, binding)
    row = (
        consumer_id, SCHEMA_VERSION, consumer_type, binding_sha256, binding_json,
        closure["snapshot_id"], closure["snapshot_manifest_sha256"],
        control_relative_path,
        canonical_json(sorted(set(str(value) for value in required_member_paths))),
        "retained", registered_at_utc or utc_now(),
    )
    control_database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(control_database)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        ensure_retained_consumer_schema(connection)
        existing = connection.execute(
            "SELECT * FROM retained_external_consumer WHERE consumer_id=?", (consumer_id,)
        ).fetchone()
        if existing is None:
            connection.execute(
                "INSERT INTO retained_external_consumer VALUES (?,?,?,?,?,?,?,?,?,?,?)", row
            )
        elif tuple(existing)[:-1] != row[:-1]:
            connection.rollback()
            raise RetainedConsumerError("retained consumer identity collision or mutable re-registration")
        connection.commit()
    return consumer_id, closure


def load_retained_consumer(control_database: Path, consumer_id: str) -> dict[str, Any]:
    with closing(sqlite3.connect(control_database)) as connection:
        connection.row_factory = sqlite3.Row
        ensure_retained_consumer_schema(connection)
        row = connection.execute(
            "SELECT * FROM retained_external_consumer WHERE consumer_id=? AND status='retained'",
            (consumer_id,),
        ).fetchone()
    if row is None:
        raise RetainedConsumerError("retained consumer is unavailable")
    return dict(row)


def resolve_retained_consumer(
    control_database: Path,
    consumer_id: str,
    *,
    snapshot_root: Callable[[str], Path],
) -> dict[str, Any]:
    row = load_retained_consumer(control_database, consumer_id)
    binding = json.loads(str(row["binding_json"]))
    if hashlib.sha256(str(row["binding_json"]).encode("utf-8")).hexdigest() != row["binding_sha256"]:
        raise RetainedConsumerError("stored retained binding hash mismatch")
    closure = inspect_dependency_closure(
        binding,
        snapshot_root=snapshot_root,
        control_relative_path=str(row["control_relative_path"]),
        required_member_paths=json.loads(str(row["required_member_paths_json"])),
    )
    closure["consumer_id"] = consumer_id
    closure["consumer_type"] = str(row["consumer_type"])
    closure["retention_classification"] = PROTECTED
    return closure


def classify_snapshot_retention(
    control_database: Path,
    snapshot_id: str,
    *,
    snapshot_root: Callable[[str], Path],
) -> dict[str, Any]:
    """Classify only; deletion remains owned by a separately governed cleanup operation."""
    with closing(sqlite3.connect(control_database)) as connection:
        ensure_retained_consumer_schema(connection)
        ids = [str(row[0]) for row in connection.execute(
            "SELECT consumer_id FROM retained_external_consumer WHERE status='retained'"
        )]
    protectors = []
    for consumer_id in ids:
        closure = resolve_retained_consumer(
            control_database, consumer_id, snapshot_root=snapshot_root
        )
        reachable = {str(row["snapshot_id"]) for row in closure.get("control_chain", [])}
        reachable.update(str(value) for value in closure.get("protected_snapshot_ids", []))
        reachable.add(str(closure["snapshot_id"]))
        if snapshot_id in reachable:
            protectors.append(consumer_id)
    return {
        "snapshot_id": snapshot_id,
        "classification": PROTECTED if protectors else ELIGIBLE,
        "protecting_consumers": sorted(protectors),
        "deletion_performed": False,
    }
