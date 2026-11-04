"""Bounded, dependency-aware lifecycle operations for ephemeral runtime work.

Runtime files are not a second source of financial truth.  This module owns
only inventory and conservative reclamation of run directories that their
producer has explicitly proved terminal and disposable.  Unknown or legacy
directories remain protected and are reported for diagnosis.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from backend.app.core.writer_runtime_ownership import classify_runtime_artifact
from backend.app.core.storage_profile import resolve_active_snapshot_pointer


@dataclass(frozen=True)
class RuntimeRetentionPolicy:
    """Operational retention for update runtime work, not financial data."""

    terminal_update_days: int = 7

    @property
    def terminal_update_age(self) -> timedelta:
        return timedelta(days=max(0, int(self.terminal_update_days)))


def _now(value: str | None = None) -> datetime:
    if value:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return datetime.now(timezone.utc)


def _tree_stats(root: Path) -> tuple[int, int]:
    files = 0
    bytes_total = 0
    if not root.exists():
        return files, bytes_total
    for path in root.rglob("*"):
        if path.is_file():
            files += 1
            try:
                bytes_total += path.stat().st_size
            except OSError:
                continue
    return files, bytes_total


def inventory_runtime_root(root: Path) -> dict[str, Any]:
    """Return a read-only physical inventory, grouped by top-level class."""

    root = Path(root)
    files, bytes_total = _tree_stats(root)
    groups: list[dict[str, Any]] = []
    if root.is_dir():
        for child in sorted(root.iterdir(), key=lambda p: p.name):
            child_files, child_bytes = _tree_stats(child)
            groups.append({
                "name": child.name,
                "kind": "directory" if child.is_dir() else "file",
                "files": child_files if child.is_dir() else (1 if child.is_file() else 0),
                "bytes": child_bytes if child.is_dir() else (child.stat().st_size if child.is_file() else 0),
            })
    return {
        "root": str(root),
        "exists": root.exists(),
        "files": files,
        "bytes": bytes_total,
        "groups": groups,
    }


def _run_roots(root: Path) -> Iterable[Path]:
    runs = Path(root) / "runs"
    if not runs.is_dir():
        return ()
    return (child for child in sorted(runs.iterdir(), key=lambda p: p.name) if child.is_dir())


def sweep_runtime_root(
    root: Path,
    *,
    active_snapshot_id: str | None = None,
    retained_snapshot_ids: set[str] | None = None,
    policy: RuntimeRetentionPolicy | None = None,
    now_utc: str | None = None,
    perform: bool = False,
) -> dict[str, Any]:
    """Classify and optionally reclaim only explicitly disposable old runs.

    ``retained_snapshot_ids`` names runtime responsibilities retained by the
    caller (for example a recovery or rollback handoff).  It is deliberately
    not the set of every immutable release retained by the publication plane:
    sealed releases own their payload and do not require the ephemeral runtime
    directory to remain available.

    ``perform`` is deliberately opt-in.  The default is an auditable dry run.
    A directory is removable only when the existing runtime classifier proves
    it is stale and the producer wrote the complete non-recovery contract.
    Unknown/legacy roots, recoverable checkpoints, the current active
    successor, and explicitly retained runtime dependencies are never removed.
    An older published successor may be removed once its owner marker proves
    that no runtime recovery/publication responsibility remains.  The sealed
    release itself is governed by its own retention roots and is not owned by
    this runtime-directory sweep.
    """

    root = Path(root)
    policy = policy or RuntimeRetentionPolicy()
    now = _now(now_utc)
    records: list[dict[str, Any]] = []
    deleted_bytes = 0
    runs_root = (root / "runs").resolve()
    for run_root in _run_roots(root):
        try:
            if run_root.resolve().parent != runs_root:
                continue
        except OSError:
            continue
        try:
            observed_at = datetime.fromtimestamp(run_root.stat().st_mtime, timezone.utc)
        except OSError:
            observed_at = now
        age = max(0.0, (now - observed_at).total_seconds())
        classification = classify_runtime_artifact(
            run_root,
            active_snapshot_id=active_snapshot_id,
            retained_snapshot_ids=retained_snapshot_ids,
            now_utc=now.isoformat().replace("+00:00", "Z"),
        )
        eligible = bool(classification.get("cleanup_eligible")) and age >= policy.terminal_update_age.total_seconds()
        record = {
            "run_root": str(run_root),
            "age_seconds": round(age, 3),
            "retention_days": policy.terminal_update_days,
            "eligible_by_age": eligible,
            "classification": classification,
            "deletion_performed": False,
        }
        if eligible and perform:
            # Recheck the exact safety predicate immediately before deletion;
            # no caller can turn an unknown or protected run into a deletion.
            latest = classify_runtime_artifact(
                run_root,
                active_snapshot_id=active_snapshot_id,
                retained_snapshot_ids=retained_snapshot_ids,
                now_utc=now.isoformat().replace("+00:00", "Z"),
            )
            if latest.get("cleanup_eligible") and run_root.is_dir():
                _files, bytes_before = _tree_stats(run_root)
                shutil.rmtree(run_root)
                record["deletion_performed"] = True
                record["deleted_bytes"] = bytes_before
                deleted_bytes += bytes_before
        records.append(record)
    return {
        "root": str(root),
        "policy": {"terminal_update_days": policy.terminal_update_days},
        "dry_run": not perform,
        "records": records,
        "eligible_count": sum(1 for item in records if item["eligible_by_age"]),
        "deleted_count": sum(1 for item in records if item["deletion_performed"]),
        "deleted_bytes": deleted_bytes,
    }


def terminal_disposal_contract(*, recovery_reusable: bool = False, disposal_proof: bool = True) -> dict[str, Any]:
    """Return the explicit producer proof required for future reclamation."""

    return {
        "recovery_reusable": bool(recovery_reusable),
        "disposal_proof": bool(disposal_proof),
        "protected_dependencies": [],
        "publication_obligation": False,
        "identity_obligation": False,
        "post_publication_disposable": False,
    }


def post_publication_disposal_contract() -> dict[str, Any]:
    """Proof for a published successor's now-unneeded runtime work."""

    contract = terminal_disposal_contract()
    contract["post_publication_disposable"] = True
    return contract


def active_component_snapshot_id(component_id: str) -> str | None:
    """Read the current component binding without mutating the control plane."""

    try:
        payload = json.loads(resolve_active_snapshot_pointer().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    for binding in payload.get("component_bindings", []):
        if binding.get("component_id") == component_id:
            value = binding.get("snapshot_id")
            return str(value) if value else None
    return None

