from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.app.core.installation_bootstrap import selected_data_root


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROFILE_PATH = PROJECT_ROOT / "config" / "fr_storage_profile.json"


@dataclass(frozen=True)
class StorageLocation:
    backend: str
    root_ref: str
    relative_location: str


@lru_cache(maxsize=1)
def load_storage_profile() -> dict[str, Any]:
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    required = {
        "storage_profile_version",
        "logical_contract_version",
        "deployment_roots",
        "control_plane",
        "identity_state",
        "logical_layers",
        "query_engine",
        "snapshot_contract",
        "partitioning",
        "file_format",
        "temporary_workspace",
        "recovery",
        "compatibility",
    }
    missing = sorted(required - profile.keys())
    if missing:
        raise ValueError(f"storage profile missing keys: {missing}")
    return profile


def resolve_deployment_root(root_ref: str) -> Path:
    root = load_storage_profile()["deployment_roots"][root_ref]
    explicit = os.environ.get(root["environment_variable"], "").strip()
    test_root = os.environ.get("FR_TEST_STORAGE_ROOT", "").strip()
    entry = str(sys.argv[0]).replace("\\", "/").lower()
    test_execution = (
        os.environ.get("FR_TEST_ISOLATION_REQUIRED") == "1"
        or "PYTEST_CURRENT_TEST" in os.environ
        or entry.endswith("/unittest/__main__.py")
        or entry.endswith("/pytest/__main__.py")
        or Path(entry).name in {"pytest", "pytest.exe", "py.test", "py.test.exe"}
        or Path(entry).name.startswith("test_")
    )
    if test_execution:
        if not test_root or not explicit:
            raise RuntimeError("isolated test storage requires explicit disposable roots")
        candidate = Path(explicit).resolve()
        boundary = Path(test_root).resolve()
        if candidate == boundary or boundary not in candidate.parents:
            raise RuntimeError("isolated test storage root is outside its disposable boundary")
    if explicit:
        return Path(explicit)
    selected = selected_data_root()
    if selected is not None:
        # A public installation owns one user-selected root.  Keep the
        # accepted local/NAS logical split below it so existing storage and
        # publication contracts remain unchanged without requiring drive
        # letters or a network share.
        child = "local" if root_ref == "local_working_root" else "data"
        return selected / child
    default = root.get("default_windows_path")
    if default:
        return Path(default)
    raise RuntimeError("configure this installation's FR storage roots before use")


def resolve_logical_layer(layer_name: str) -> StorageLocation:
    layer = load_storage_profile()["logical_layers"][layer_name]
    return StorageLocation(
        backend=layer["backend"],
        root_ref=layer["root_ref"],
        relative_location=layer["relative_location"],
    )


def resolve_logical_layer_path(layer_name: str) -> Path:
    location = resolve_logical_layer(layer_name)
    return resolve_deployment_root(location.root_ref) / location.relative_location


def resolve_compatibility_source(source_name: str) -> Path:
    source = load_storage_profile()["compatibility"][source_name]
    return resolve_deployment_root(source["root_ref"]) / source["relative_location"]


def resolve_control_plane_path() -> Path:
    control = load_storage_profile()["control_plane"]
    return resolve_deployment_root(control["root_ref"]) / control["relative_location"]


def resolve_unpublished_control_path(snapshot_id: str) -> Path:
    if not snapshot_id or any(token in snapshot_id for token in ("/", "\\", "..")):
        raise ValueError("snapshot_id must be one path-safe segment")
    control = load_storage_profile()["control_plane"]
    return (
        resolve_deployment_root(control["root_ref"])
        / "control"
        / "unpublished"
        / snapshot_id
        / "fr_control_v1.sqlite"
    )


def resolve_temporary_workspace_path(namespace: str | None = None) -> Path:
    temporary = load_storage_profile()["temporary_workspace"]
    root = resolve_deployment_root(temporary["root_ref"]) / temporary["relative_location"]
    if namespace is None:
        return root
    if not namespace or any(token in namespace for token in ("/", "\\", "..")):
        raise ValueError("temporary-workspace namespace must be one path-safe segment")
    return root / namespace


def resolve_serving_derived_path(namespace: str | None = None) -> Path:
    serving = load_storage_profile()["serving_derived"]
    root = resolve_deployment_root(serving["root_ref"]) / serving["relative_location"]
    if namespace is None:
        return root
    if not namespace or any(token in namespace for token in ("/", "\\", "..")):
        raise ValueError("serving-derived namespace must be one path-safe segment")
    return root / namespace


def resolve_identity_state_path() -> Path:
    identity = load_storage_profile()["identity_state"]
    return resolve_deployment_root(identity["root_ref"]) / identity["relative_location"]


def resolve_identity_state_backup_root() -> Path:
    identity = load_storage_profile()["identity_state"]
    return resolve_deployment_root(identity["root_ref"]) / identity["backup_relative_location"]


def resolve_identity_state_mirror_root() -> Path:
    identity = load_storage_profile()["identity_state"]
    return resolve_deployment_root(identity["mirror_root_ref"]) / identity["mirror_relative_location"]


def resolve_active_snapshot_pointer() -> Path:
    snapshot = load_storage_profile()["snapshot_contract"]
    return resolve_deployment_root(snapshot["active_pointer_root_ref"]) / snapshot["active_pointer_relative_location"]


def resolve_rollback_descriptor_path() -> Path:
    snapshot = load_storage_profile()["snapshot_contract"]
    return resolve_deployment_root(snapshot["active_pointer_root_ref"]) / snapshot["rollback_descriptor_relative_location"]


def resolve_serving_release_registry_path() -> Path:
    snapshot = load_storage_profile()["snapshot_contract"]
    return resolve_deployment_root(snapshot["active_pointer_root_ref"]) / snapshot["serving_release_registry_relative_location"]


def resolve_read_model_release_path(release_id: str) -> Path:
    if not release_id or any(token in release_id for token in ("/", "\\", "..")):
        raise ValueError("release_id must be one path-safe segment")
    return resolve_logical_layer_path("read_models") / release_id


def resolve_unpublished_snapshot_path(snapshot_id: str) -> Path:
    if not snapshot_id or any(token in snapshot_id for token in ("/", "\\", "..")):
        raise ValueError("snapshot_id must be one path-safe segment")
    return resolve_deployment_root("nas_publish_root") / "snapshots" / "unpublished" / snapshot_id
