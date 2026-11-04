"""Atomic compare-and-swap transitions for the authoritative serving pointer."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Mapping

from backend.app.core.artifact_io import canonical_json, write_json_atomic
from backend.app.core.diagnostics import log_event
from backend.app.core.retained_consumer import resolve_retained_consumer
from backend.app.core.serving_release import RELEASE_SCHEMA_V2, pin_serving_release, verify_release_descriptor
from backend.app.core.storage_profile import resolve_unpublished_snapshot_path


class ServingPublicationError(RuntimeError):
    pass


class StaleActiveRelease(ServingPublicationError):
    pass


class InjectedServingTransitionFailure(ServingPublicationError):
    pass


class ServingTransitionAcknowledgementLost(ServingPublicationError):
    pass


def descriptor_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def ensure_serving_transition_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS serving_release_transition(
          operation_id TEXT PRIMARY KEY,
          operation_type TEXT NOT NULL,
          expected_active_sha256 TEXT NOT NULL,
          prior_active_sha256 TEXT NOT NULL,
          target_release_id TEXT,
          target_release_sha256 TEXT NOT NULL,
          retention_consumer_id TEXT NOT NULL,
          status TEXT NOT NULL,
          committed_at_utc TEXT NOT NULL
        )"""
    )


def has_committed_serving_transition(control_database: Path) -> bool:
    """Read prior publication evidence without creating control-plane state."""
    if not control_database.is_file():
        return False
    with closing(sqlite3.connect(f"file:{control_database.resolve().as_posix()}?mode=ro", uri=True)) as connection:
        try:
            row = connection.execute(
                "SELECT 1 FROM serving_release_transition "
                "WHERE status IN ('committed', 'already_active') LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return False
            raise
    return row is not None


def _verify_target(
    target: Mapping[str, Any],
    *,
    retention_consumer_id: str,
    control_database: Path,
    snapshot_root: Callable[[str], Path],
) -> dict[str, Any]:
    target_value = dict(target)
    if target_value.get("schema_version") == RELEASE_SCHEMA_V2:
        verify_release_descriptor(target_value, snapshot_root=snapshot_root)
    closure = resolve_retained_consumer(
        control_database, retention_consumer_id, snapshot_root=snapshot_root,
    )
    with closing(sqlite3.connect(f"file:{control_database.as_posix()}?mode=ro", uri=True)) as connection:
        row = connection.execute(
            "SELECT binding_json,status FROM retained_external_consumer WHERE consumer_id=?",
            (retention_consumer_id,),
        ).fetchone()
    if row is None or row[1] != "retained":
        raise ServingPublicationError("target release has no retained dependency closure")
    retained = json.loads(row[0])
    if retained.get("release_descriptor") != target_value:
        raise ServingPublicationError("retention root does not bind the exact target release")
    return closure


def _maintain_derived_serving(active_pointer: Path) -> None:
    """Maintain the derived serving generation after a pointer transition.

    Runs after a committed publication/rollback through the existing
    publication owner.  Unchanged source members reuse their immutable
    indexed shards; changed/new members build only their own.  A failure
    here never fails the pointer transition: the previous serving generation
    stays active, and serving falls back to the production Parquet path
    until a verified generation is ready.
    """
    from backend.app.core.china_equity_query import COMPONENT_ID, ChinaEquitySnapshot
    from backend.app.core.china_equity_serving_store import maintain_generation

    release = pin_serving_release(active_pointer)
    if release.release_type != "composite_serving_release" or not release.snapshot_id:
        return
    snapshot = ChinaEquitySnapshot.from_release(release)
    maintain_generation(
        release={
            "release_id": release.release_id,
            "release_hash": release.release_hash,
            "snapshot_id": release.snapshot_id,
        },
        snapshot_root=snapshot.snapshot_root,
        manifest=snapshot.manifest,
        manifest_sha256=str(release.component(COMPONENT_ID).get("manifest_sha256") or ""),
        database_generation_id=str(release.database_generation_id or ""),
    )


def transition_active_release(
    *,
    active_pointer: Path,
    control_database: Path,
    target_release: Mapping[str, Any],
    target_retention_consumer_id: str,
    expected_active_sha256: str,
    operation_id: str,
    operation_type: str,
    committed_at_utc: str,
    snapshot_root: Callable[[str], Path] = resolve_unpublished_snapshot_path,
    failure_point: str | None = None,
    allow_initial_publication: bool = False,
) -> dict[str, Any]:
    """CAS the active descriptor after proving the target dependency closure.

    The pointer file is authoritative.  SQLite serializes participating writers
    and retains a non-authoritative audit row.  If acknowledgement is lost
    after atomic replacement, a retry observes the exact target bytes and is a
    safe idempotent success.
    """
    if operation_type not in {"publication", "rollback"}:
        raise ValueError("operation_type must be publication or rollback")
    if failure_point not in {None, "before_pointer", "after_pointer_before_audit", "after_pointer_before_ack"}:
        raise ValueError("unsupported failure point")
    initial_publication = not active_pointer.is_file()
    if initial_publication and not allow_initial_publication:
        raise ServingPublicationError("active serving pointer is unavailable")
    if initial_publication and expected_active_sha256:
        raise ServingPublicationError("initial publication requires an empty expected-active hash")
    closure = _verify_target(
        target_release, retention_consumer_id=target_retention_consumer_id,
        control_database=control_database, snapshot_root=snapshot_root,
    )
    if operation_type == "publication":
        # Rollback must preserve legacy immutable views. New continuing Equity
        # publication, including callers below the normal workflow, may not
        # bypass semantic completion by omitting its receipt.
        from backend.app.core.subject_graph_projection import verify_subject_graph_completion
        for component in target_release.get("component_bindings", []):
            if component.get("component_id") != "CN_A_SHARE":
                continue
            root = snapshot_root(str(component["snapshot_id"]))
            manifest_path = root / "metadata/corrected_candidate_manifest_v1.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("schema_version") == "fr_a_share_foundation_continuing_successor_manifest_v1":
                verify_subject_graph_completion(root)
    target_bytes = descriptor_bytes(target_release)
    target_sha = bytes_sha256(target_bytes)
    control_database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(control_database)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        ensure_serving_transition_schema(connection)
        prior = active_pointer.read_bytes() if active_pointer.is_file() else b""
        prior_sha = bytes_sha256(prior)
        existing = connection.execute(
            "SELECT target_release_sha256,status FROM serving_release_transition WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if existing is not None and existing[0] != target_sha:
            connection.rollback()
            raise ServingPublicationError("operation identity was reused for a different target")
        if prior == target_bytes:
            if existing is None or existing[1] == "prepared":
                connection.execute(
                    "INSERT OR REPLACE INTO serving_release_transition VALUES (?,?,?,?,?,?,?,?,?)",
                    (operation_id, operation_type, expected_active_sha256, prior_sha,
                     target_release.get("release_id"), target_sha, target_retention_consumer_id,
                     "already_active", committed_at_utc),
                )
            connection.commit()
            return {
                "status": "already_active", "operation_id": operation_id,
                "prior_active_sha256": prior_sha, "active_sha256": target_sha,
                "pointer_changed": False, "retention_closure": closure,
            }
        if not initial_publication and prior_sha != expected_active_sha256:
            connection.rollback()
            raise StaleActiveRelease("active serving release compare-and-swap failed")
        if failure_point == "before_pointer":
            connection.rollback()
            raise InjectedServingTransitionFailure("injected failure before authoritative pointer replacement")
        # Record the exact target and operation before the pointer swap.  The
        # pointer remains authoritative; a prepared row alone is never proof
        # of publication.  It lets restart reconcile the narrow crash window
        # after atomic replacement but before the audit row is committed.
        connection.execute(
            "INSERT OR REPLACE INTO serving_release_transition VALUES (?,?,?,?,?,?,?,?,?)",
            (operation_id, operation_type, expected_active_sha256, prior_sha,
             target_release.get("release_id"), target_sha, target_retention_consumer_id,
             "prepared", committed_at_utc),
        )
        connection.commit()
        connection.execute("BEGIN IMMEDIATE")
        current = active_pointer.read_bytes() if active_pointer.is_file() else b""
        if current != prior:
            connection.rollback()
            raise StaleActiveRelease("active release changed after publication intent was prepared")
        write_json_atomic(active_pointer, dict(target_release))
        if failure_point == "after_pointer_before_audit":
            raise InjectedServingTransitionFailure(
                "injected interruption after authoritative pointer replacement before audit commit"
            )
        connection.execute(
            "INSERT OR REPLACE INTO serving_release_transition VALUES (?,?,?,?,?,?,?,?,?)",
            (operation_id, operation_type, expected_active_sha256, prior_sha,
             target_release.get("release_id"), target_sha, target_retention_consumer_id,
             "committed", committed_at_utc),
        )
        connection.commit()
    if failure_point == "after_pointer_before_ack":
        raise ServingTransitionAcknowledgementLost(
            "authoritative pointer committed but success acknowledgement was intentionally lost"
        )
    try:
        _maintain_derived_serving(active_pointer)
    except Exception as exc:
        log_event(
            "derived_serving_maintenance_failed",
            level=30,
            stage="derived_serving_maintenance",
            operation_id=operation_id,
            error=str(exc)[:300],
        )
    return {
        "status": "committed", "operation_id": operation_id,
        "prior_active_sha256": prior_sha, "active_sha256": target_sha,
        "pointer_changed": True, "initial_publication": initial_publication,
        "retention_closure": closure,
    }
