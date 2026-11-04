"""Registry-bound component ownership independent of the Fund/Equity V1 pair.

The registry describes *possible* governed component owners. A registered
candidate is not a serving release; publication also requires a validated
immutable snapshot, component closure, release contracts and the normal CAS.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from backend.app.core.artifact_io import sha256_file


ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = ROOT / "config/fr_governed_component_registry.json"
VOCABULARY_PATH = ROOT / "config/fr_data_category_registry.json"
REGISTRY_SCHEMA = "fr_governed_component_registry_v1"
AUTHORITY_SCHEMA = "fr_release_component_authority_v1"
LEGACY_COMPONENTS = frozenset({"CN_PUBLIC_FUND", "CN_A_SHARE"})


@dataclass(frozen=True)
class GovernedComponent:
    component_id: str
    universe_id: str
    scope: str
    serving_enabled: bool
    compatibility_id: bool


def load_governed_components(
    path: Path = REGISTRY_PATH, *, vocabulary_path: Path = VOCABULARY_PATH,
) -> tuple[dict[str, GovernedComponent], str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != REGISTRY_SCHEMA:
        raise ValueError("unsupported governed component registry")
    vocabulary = json.loads(vocabulary_path.read_text(encoding="utf-8"))
    universe_ids = {row["universe_id"] for row in vocabulary["universe_vocabulary"]["universes"]}
    rows = payload.get("components")
    if not isinstance(rows, list) or not rows:
        raise ValueError("governed component registry is empty")
    result: dict[str, GovernedComponent] = {}
    for raw in rows:
        component = GovernedComponent(**raw)
        if not component.component_id or component.component_id in result:
            raise ValueError("missing or duplicate governed component ID")
        if component.universe_id not in universe_ids or not component.scope:
            raise ValueError(f"invalid financial owner: {component.component_id}")
        if component.compatibility_id != (component.component_id in LEGACY_COMPONENTS):
            raise ValueError(f"incorrect legacy compatibility status: {component.component_id}")
        result[component.component_id] = component
    if not LEGACY_COMPONENTS <= result.keys():
        raise ValueError("Fund/Equity compatibility components are missing")
    return result, sha256_file(path)


def release_component_authority(
    selected_ids: set[str], *, registry: Mapping[str, GovernedComponent], registry_sha256: str,
) -> dict[str, Any]:
    """Freeze owner semantics in a new release; later registry edits do not rewrite it."""
    if not selected_ids or selected_ids - registry.keys():
        raise ValueError("release contains an unregistered component")
    disabled = sorted(key for key in selected_ids if not registry[key].serving_enabled)
    if disabled:
        raise ValueError(f"components are registered for candidates but not serving: {disabled}")
    return {
        "schema_version": AUTHORITY_SCHEMA,
        "registry_sha256": registry_sha256,
        "components": [
            {"component_id": key, "universe_id": registry[key].universe_id,
             "scope": registry[key].scope, "compatibility_id": registry[key].compatibility_id}
            for key in sorted(selected_ids)
        ],
    }


def select_component_snapshots(
    active_bindings: list[Mapping[str, Any]],
    replacements: Mapping[str, str],
    *,
    registry: Mapping[str, GovernedComponent],
) -> dict[str, str]:
    """Preserve unrelated component bindings while selecting changed heads.

    The physical integrated snapshot is validated separately. Selection is a
    release operation, so a candidate-only registry entry cannot enter it.
    """
    selected: dict[str, str] = {}
    for row in active_bindings:
        key, snapshot = str(row.get("component_id") or ""), str(row.get("snapshot_id") or "")
        if not key or not snapshot or key in selected:
            raise ValueError("active release has invalid component bindings")
        if key not in registry:
            raise ValueError(f"active release component is unregistered: {key}")
        selected[key] = snapshot
    if not selected:
        raise ValueError("active release has no components")
    for key in sorted(replacements):
        snapshot = str(replacements[key] or "")
        if key not in registry:
            raise ValueError(f"replacement component is unregistered: {key}")
        if not registry[key].serving_enabled:
            raise ValueError(f"component is registered for candidates but not serving: {key}")
        if not snapshot:
            raise ValueError(f"replacement component has no snapshot: {key}")
        selected[key] = snapshot
    return selected


def validate_embedded_component_authority(
    bound_component_ids: set[str], authority: Mapping[str, Any] | None,
) -> None:
    """Keep historical V1 descriptors readable; new owners need frozen proof."""
    if authority is None:
        if bound_component_ids - LEGACY_COMPONENTS:
            raise ValueError("new component lacks release-bound owner authority")
        return
    if authority.get("schema_version") != AUTHORITY_SCHEMA:
        raise ValueError("unsupported release component authority")
    digest = authority.get("registry_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("component registry digest is missing")
    rows = authority.get("components")
    if not isinstance(rows, list):
        raise ValueError("component authority rows are missing")
    ids = [row.get("component_id") for row in rows]
    if set(ids) != bound_component_ids or len(ids) != len(bound_component_ids):
        raise ValueError("component authority differs from release bindings")
    for row in rows:
        if not row.get("universe_id") or not row.get("scope"):
            raise ValueError("component financial owner is missing")
        if bool(row.get("compatibility_id")) != (row["component_id"] in LEGACY_COMPONENTS):
            raise ValueError("component compatibility ownership changed")
