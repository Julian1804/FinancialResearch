"""Durable, product-facing lifecycle readback for accepted update workflows.

This module deliberately records only application lifecycle facts.  It does not
replace the writer lease, validated-head repositories, runtime markers, or the
active-release pointer.  Those owners remain authoritative for their own
semantics; this store makes their final product outcome discoverable after a
lost HTTP response or a browser reload.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.app.core.diagnostic_safety import redact_value
from backend.app.core.storage_profile import resolve_active_snapshot_pointer, resolve_control_plane_path


SCHEMA_VERSION = "fr_product_operation_lifecycle_v1"
OPERATION_TYPES = {"first_install", "fund_update", "china_equity_update", "configured_update"}
SCOPES = {"installation", "Fund", "Equity"}
STATES = {
    "running",
    "blocked",
    "published",
    "no_material_change",
    "failed",
    "busy",
    "interrupted_recoverable",
    "interrupted_unresolved",
}
COMPONENT_BY_SCOPE = {"Fund": "CN_PUBLIC_FUND", "Equity": "CN_A_SHARE"}


class OperationRegistrationUnavailable(RuntimeError):
    """The product could not durably register an accepted operation."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _active_payload() -> dict[str, Any] | None:
    pointer = resolve_active_snapshot_pointer()
    if not pointer.is_file():
        return None
    try:
        value = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def active_serving_view() -> dict[str, Any]:
    """Return safe active-release and per-component serving facts."""

    pointer = _active_payload()
    if not pointer or pointer.get("release_type") != "composite_serving_release":
        return {
            "status": "unavailable",
            "release_id": None,
            "release_hash": None,
            "snapshot_id": None,
            "database_generation_id": None,
            "components": {},
            "reason": "active_composite_release_unavailable",
        }
    components: dict[str, dict[str, Any]] = {}
    for row in pointer.get("component_bindings", []):
        if not isinstance(row, Mapping) or not row.get("component_id"):
            continue
        component_id = str(row["component_id"])
        component = {
            "component_id": component_id,
            "snapshot_id": row.get("snapshot_id"),
            "manifest_sha256": row.get("manifest_sha256"),
            "database_generation_id": row.get("database_generation_id") or pointer.get("database_generation_id"),
            "status": "available" if row.get("snapshot_id") and row.get("manifest_sha256") else "unavailable",
        }
        components[component_id] = component
    return {
        "status": "available" if pointer.get("snapshot_id") and components else "unavailable",
        "release_id": pointer.get("release_id"),
        "release_hash": pointer.get("release_content_hash") or pointer.get("content_hash"),
        "snapshot_id": pointer.get("snapshot_id"),
        "manifest_sha256": pointer.get("snapshot_manifest_sha256"),
        "database_generation_id": pointer.get("database_generation_id"),
        "components": components,
        "reason": None,
    }


def _component_view(active: Mapping[str, Any], scope: str) -> dict[str, Any]:
    component_id = COMPONENT_BY_SCOPE.get(scope)
    component = dict((active.get("components") or {}).get(component_id) or {})
    if not component:
        return {
            "scope": scope,
            "component_id": component_id,
            "status": "unavailable",
            "queryable": False,
            "snapshot_id": None,
            "manifest_sha256": None,
        }
    return {
        "scope": scope,
        "component_id": component_id,
        "status": component.get("status", "unavailable"),
        "queryable": component.get("status") == "available" and active.get("status") == "available",
        "snapshot_id": component.get("snapshot_id"),
        "manifest_sha256": component.get("manifest_sha256"),
        "database_generation_id": component.get("database_generation_id"),
    }


def _writer_lease_for_operation(database_path: Path, operation_id: str) -> str | None:
    """Return a non-sensitive *active lease* liveness label for one operation.

    The owner fields on the lifecycle row are historical context only.  They
    are deliberately not a fallback ownership proof: a long-lived API process
    may outlive the operation whose row it created.
    """
    if not database_path.is_file():
        return None
    row = None
    with closing(sqlite3.connect(f"file:{database_path.resolve().as_posix()}?mode=ro", uri=True)) as connection:
        try:
            row = connection.execute(
                "SELECT operation_id,pid,process_instance_id,status FROM fr_installation_writer_lease WHERE singleton_id=1"
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
    try:
        from backend.app.core.writer_runtime_ownership import _owner_liveness
    except Exception:
        return "unknown_owner"
    if row and str(row[0]) != operation_id and str(row[3]) == "active":
        owner_state = _owner_liveness(int(row[1]), row[2])
        if owner_state == "alive":
            return "other_live_owner"
        if owner_state in {"ambiguous", "unknown"}:
            return "unknown_owner" if owner_state == "unknown" else "ambiguous"
        return None
    try:
        if row and str(row[0]) == operation_id and str(row[3]) == "active":
            owner_state = _owner_liveness(int(row[1]), row[2])
            return None if owner_state == "dead" else owner_state
        # ``operation_row`` is intentionally not consulted here.  PID/process
        # identity on a completed-or-orphaned lifecycle row does not establish
        # current execution ownership.
        return None
    except Exception:
        return "unknown_owner"


def _publication_transition_for_operation(database_path: Path, operation_id: str) -> dict[str, Any] | None:
    """Read the accepted publication audit row for one lifecycle operation.

    ``serving_release_transition`` is the existing publication audit owned by
    the CAS primitive, not a second operation ledger.  The operation-id
    prefixes are stable for normal updates and first-install publication; the
    latter also accepts the legacy release-based prefix for compatibility when
    the lifecycle row already records that release.
    """
    if not database_path.is_file():
        return None
    candidates = (f"normal_update_publication:{operation_id}", f"initial_publication:{operation_id}")
    with closing(sqlite3.connect(f"file:{database_path.resolve().as_posix()}?mode=ro", uri=True)) as connection:
        try:
            rows = connection.execute(
                "SELECT operation_id,target_release_id,target_release_sha256,status,committed_at_utc "
                "FROM serving_release_transition WHERE operation_id IN (?,?) ORDER BY committed_at_utc DESC",
                candidates,
            ).fetchall()
        except sqlite3.OperationalError:
            return None
    for row in rows:
        if str(row[3]) in {"committed", "already_active"}:
            return {
                "operation_id": str(row[0]),
                "target_release_id": row[1],
                "target_release_sha256": row[2],
                "status": row[3],
                "committed_at_utc": row[4],
            }
    # A crash may occur after the authoritative pointer replacement but
    # before the non-authoritative transition row becomes committed.  A
    # prepared intent is proof only if the target is/was physically active.
    # The later committed transition's prior hash preserves that proof even
    # after another release supersedes the target.
    prepared = next((row for row in rows if str(row[3]) == "prepared"), None)
    if prepared is not None:
        target_hash = str(prepared[2])
        pointer = _active_payload()
        current_hash = None
        if pointer is not None:
            from backend.app.core.serving_publication import bytes_sha256, descriptor_bytes
            current_hash = bytes_sha256(descriptor_bytes(pointer))
        with closing(sqlite3.connect(f"file:{database_path.resolve().as_posix()}?mode=ro", uri=True)) as connection:
            later = connection.execute(
                "SELECT 1 FROM serving_release_transition WHERE prior_active_sha256=? "
                "AND status IN ('committed','already_active') LIMIT 1", (target_hash,),
            ).fetchone()
        if current_hash == target_hash or later is not None:
            return {
                "operation_id": str(prepared[0]), "target_release_id": prepared[1],
                "target_release_sha256": target_hash, "status": "pointer_proved_after_prepared_intent",
                "committed_at_utc": None,
            }
    return None


def _runtime_marker(runtime_root: Any) -> dict[str, Any] | None:
    if not runtime_root:
        return None
    marker_path = Path(str(runtime_root)) / "runtime_owner_v1.json"
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8")) if marker_path.is_file() else None
    except (OSError, json.JSONDecodeError):
        return None
    return marker if isinstance(marker, dict) else None


def _effective_row(row: Mapping[str, Any], active: Mapping[str, Any], *, database_path: Path | None = None) -> dict[str, Any]:
    """Project an interrupted stored ``running`` row into a safe product state.

    This is deliberately read-only.  The next owner/recovery path remains the
    authority that commits a terminal operation result.
    """
    value = dict(row)
    control_database = database_path or resolve_control_plane_path()
    operation_id = str(value["operation_id"])
    publication = _publication_transition_for_operation(control_database, operation_id)
    if publication is not None:
        value["stored_status"] = value.get("status")
        value["status"] = "published"
        value["outcome_code"] = "published"
        value["reason_code"] = "durable_publication_transition"
        value["publication_status"] = "published_or_response_lost"
        value["successor_release_id"] = value.get("successor_release_id") or publication.get("target_release_id")
        value["recoverable"] = False
        value["retryable"] = False
        detail = dict(value.get("detail") or {})
        detail["publication_transition"] = {
            "status": publication.get("status"),
            "release_id": publication.get("target_release_id"),
            "release_hash": publication.get("target_release_sha256"),
            "committed_at_utc": publication.get("committed_at_utc"),
        }
        value["detail"] = detail
        value["effective_state_reason"] = "durable_publication_transition"
        return value
    if value.get("status") != "running":
        return value
    value["stored_status"] = "running"
    lease_state = _writer_lease_for_operation(control_database, operation_id)
    if lease_state == "alive":
        value["effective_state_reason"] = "writer_owner_live" if lease_state == "alive" else "writer_owner_identity_ambiguous"
        return value
    if lease_state in {"ambiguous", "other_live_owner", "unknown_owner"}:
        value["status"] = "interrupted_unresolved"
        value["outcome_code"] = "interrupted_unresolved"
        value["reason_code"] = {
            "ambiguous": "writer_owner_identity_ambiguous",
            "other_live_owner": "writer_owned_by_other_operation",
            "unknown_owner": "writer_owner_state_unknown",
        }[lease_state]
        value["recoverable"] = False
        value["retryable"] = False
        value["effective_state_reason"] = value["reason_code"]
        return value
    runtime_root = value.get("_runtime_root")
    marker = _runtime_marker(runtime_root)
    component_id = COMPONENT_BY_SCOPE.get(str(value.get("scope")))
    component = (active.get("components") or {}).get(component_id) or {}
    successor = marker.get("successor_snapshot_id") if marker else None
    if successor and successor == component.get("snapshot_id") and component.get("status") == "available":
        value["status"] = "published"
        value["outcome_code"] = "published"
        value["reason_code"] = "successor_component_is_active"
        value["publication_status"] = "published_or_response_lost"
        value["active_release_id"] = active.get("release_id")
        value["active_release_hash"] = active.get("release_hash")
        value["active_snapshot_id"] = active.get("snapshot_id")
        value["recoverable"] = False
        value["retryable"] = False
        value["effective_state_reason"] = "runtime_successor_is_active"
        return value
    if runtime_root:
        try:
            from backend.app.core.writer_runtime_ownership import classify_runtime_artifact

            classification = classify_runtime_artifact(
                Path(str(runtime_root)),
                active_snapshot_id=active.get("snapshot_id"),
                retained_snapshot_ids=set(),
            )
            recovery = classification.get("recovery") or {}
            if recovery.get("status") == "reusable" or classification.get("classification") == "reusable":
                value["status"] = "interrupted_recoverable"
                value["outcome_code"] = "interrupted_recoverable"
                value["reason_code"] = str(recovery.get("reason") or classification.get("reason") or "accepted_recovery_contract")
                value["recoverable"] = True
                value["retryable"] = True
                value["effective_state_reason"] = "accepted_runtime_recovery_contract"
                return value
        except Exception:
            pass
    value["status"] = "interrupted_unresolved"
    value["outcome_code"] = "interrupted_unresolved"
    value["reason_code"] = "operation_owner_not_live_and_recovery_not_proved"
    value["recoverable"] = False
    value["retryable"] = False
    value["effective_state_reason"] = "owner_not_live_recovery_unresolved"
    return value


class OperationLifecycleStore:
    """Small durable registry in the existing control plane.

    The table is an application read model, not a second publication or fact
    authority.  Every mutation advances a monotone revision used by polling
    clients to reject stale responses.
    """

    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = Path(database_path) if database_path else resolve_control_plane_path()

    @staticmethod
    def _schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS fr_product_operation_lifecycle(
                operation_id TEXT PRIMARY KEY,
                operation_type TEXT NOT NULL,
                scope TEXT NOT NULL,
                status TEXT NOT NULL,
                outcome_code TEXT,
                reason_code TEXT,
                error_class TEXT,
                retryable INTEGER NOT NULL DEFAULT 0,
                recoverable INTEGER NOT NULL DEFAULT 0,
                serving_unchanged INTEGER,
                started_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL,
                completed_at_utc TEXT,
                predecessor_release_id TEXT,
                predecessor_snapshot_id TEXT,
                successor_release_id TEXT,
                successor_snapshot_id TEXT,
                active_release_id TEXT,
                active_release_hash TEXT,
                active_snapshot_id TEXT,
                changed_component TEXT,
                publication_status TEXT,
                runtime_root TEXT,
                request_id TEXT,
                owner_pid INTEGER,
                owner_process_instance_id TEXT,
                detail_json TEXT NOT NULL,
                revision INTEGER NOT NULL
            )"""
        )
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(fr_product_operation_lifecycle)")}
        if "owner_pid" not in columns:
            connection.execute("ALTER TABLE fr_product_operation_lifecycle ADD COLUMN owner_pid INTEGER")
        if "owner_process_instance_id" not in columns:
            connection.execute("ALTER TABLE fr_product_operation_lifecycle ADD COLUMN owner_process_instance_id TEXT")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_fr_product_operation_scope_revision "
            "ON fr_product_operation_lifecycle(scope, revision DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_fr_product_operation_updated "
            "ON fr_product_operation_lifecycle(updated_at_utc DESC)"
        )

    def _next_revision(self, connection: sqlite3.Connection) -> int:
        row = connection.execute("SELECT COALESCE(MAX(revision), 0) + 1 FROM fr_product_operation_lifecycle").fetchone()
        return int(row[0])

    def _write(self, operation_id: str, values: Mapping[str, Any], *, insert_if_missing: bool = True) -> dict[str, Any]:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database_path, timeout=30)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._schema(connection)
            existing = connection.execute(
                "SELECT operation_id,started_at_utc FROM fr_product_operation_lifecycle WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if existing is None and not insert_if_missing:
                connection.rollback()
                raise KeyError(operation_id)
            now = _now()
            payload = dict(values)
            payload.setdefault("started_at_utc", existing[1] if existing else now)
            payload["updated_at_utc"] = now
            payload["revision"] = self._next_revision(connection)
            if existing is None:
                columns = ["operation_id", *payload.keys()]
                placeholders = ",".join("?" for _ in columns)
                connection.execute(
                    f"INSERT INTO fr_product_operation_lifecycle({','.join(columns)}) VALUES({placeholders})",
                    (operation_id, *[payload[column] for column in payload]),
                )
            else:
                assignments = ",".join(f"{column}=?" for column in payload)
                connection.execute(
                    f"UPDATE fr_product_operation_lifecycle SET {assignments} WHERE operation_id=?",
                    (*[payload[column] for column in payload], operation_id),
                )
            connection.commit()
        return self.get(operation_id) or {}

    def begin(
        self,
        operation_id: str,
        *,
        operation_type: str,
        scope: str,
        predecessor: Mapping[str, Any] | None = None,
        runtime_root: Path | str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if operation_type not in OPERATION_TYPES:
            raise ValueError(f"unsupported operation type: {operation_type}")
        if scope not in SCOPES:
            raise ValueError(f"unsupported operation scope: {scope}")
        existing = self.get(operation_id)
        if existing:
            return existing
        active = active_serving_view()
        from backend.app.core.writer_runtime_ownership import process_identity

        identity = process_identity()
        values = {
            "operation_type": operation_type,
            "scope": scope,
            "status": "running",
            "outcome_code": None,
            "reason_code": None,
            "error_class": None,
            "retryable": 0,
            "recoverable": 0,
            "serving_unchanged": None,
            "completed_at_utc": None,
            "predecessor_release_id": active.get("release_id"),
            "predecessor_snapshot_id": (predecessor or {}).get("snapshot_id") or ((active.get("components") or {}).get(COMPONENT_BY_SCOPE.get(scope, "")) or {}).get("snapshot_id"),
            "successor_release_id": None,
            "successor_snapshot_id": None,
            "active_release_id": active.get("release_id"),
            "active_release_hash": active.get("release_hash"),
            "active_snapshot_id": active.get("snapshot_id"),
            "changed_component": COMPONENT_BY_SCOPE.get(scope),
            "publication_status": None,
            "runtime_root": str(runtime_root) if runtime_root else None,
            "request_id": request_id,
            "owner_pid": identity.get("pid") or os.getpid(),
            "owner_process_instance_id": identity.get("process_instance_id"),
            "detail_json": _json({"schema_version": SCHEMA_VERSION}),
        }
        return self._write(operation_id, values)

    def transition(self, operation_id: str, result: Mapping[str, Any], *, operation_type: str, scope: str) -> dict[str, Any]:
        """Record one accepted owner result without storing raw exceptions or paths."""

        result_value = str(result.get("result") or result.get("status") or "failed")
        publication = result.get("publication") if isinstance(result.get("publication"), Mapping) else {}
        nested = result.get("update_result") if isinstance(result.get("update_result"), Mapping) else {}
        effective = {**nested, **dict(result)}
        publication_status = str(publication.get("status") or publication.get("result") or "") or None
        if result_value in {"blocked"} or str(result.get("error_code")) == "no_data_scope_configured":
            status = "blocked"
        elif result_value in {"busy", "conflict"} or str(result.get("status")) == "busy":
            status = "busy"
        elif result_value == "no_material_change" or bool(result.get("no_op")) or publication.get("reason") == "no_material_change":
            status = "no_material_change"
        elif str(result.get("status")) == "success" or result_value in {"success", "PASS"}:
            status = "published"
        else:
            status = "failed"
        error_class = str(result.get("error_class") or "") or None
        outcome_code = "no_material_change" if status == "no_material_change" else ("published" if status == "published" else status)
        reason_code = str(
            result.get("error_type")
            or result.get("error_code")
            or result.get("code")
            or publication.get("reason")
            or (result_value if result_value not in {"success", "PASS", "failed"} else None)
            or outcome_code
        )
        active = active_serving_view()
        predecessor = effective.get("predecessor_snapshot_id")
        successor = effective.get("successor_snapshot_id") or result.get("snapshot_id")
        if status == "no_material_change":
            unchanged = True
        elif status in {"failed", "busy", "blocked"}:
            unchanged = not bool(result.get("active_pointer_changed")) and active.get("status") == "available"
        else:
            unchanged = bool(result.get("active_pointer_unchanged"))
        retryable = bool(result.get("retryable", status in {"failed", "busy", "interrupted_recoverable"}))
        recoverable = bool(result.get("recoverable", status == "interrupted_recoverable"))
        existing = self.get(operation_id)
        details = {
            **dict((existing or {}).get("detail") or {}),
            "schema_version": SCHEMA_VERSION,
            "outcome": outcome_code,
            "reason": reason_code,
            "error_type": result.get("error_type") or result.get("error_code"),
            "writer_operation_id": result.get("writer_operation_id"),
        }
        values = {
            "operation_type": operation_type,
            "scope": scope,
            "status": status,
            "outcome_code": outcome_code,
            "reason_code": reason_code,
            "error_class": error_class,
            "retryable": int(retryable),
            "recoverable": int(recoverable),
            "serving_unchanged": int(unchanged) if unchanged is not None else None,
            "completed_at_utc": _now(),
            "successor_release_id": result.get("active_release_id") or result.get("release_id"),
            "successor_snapshot_id": successor,
            "active_release_id": active.get("release_id") or result.get("active_release_id") or result.get("release_id"),
            "active_release_hash": active.get("release_hash") or result.get("active_release_hash") or result.get("release_hash"),
            "active_snapshot_id": active.get("snapshot_id") or result.get("active_snapshot_id"),
            "changed_component": publication.get("changed_component") or COMPONENT_BY_SCOPE.get(scope),
            "publication_status": publication_status or ("not_attempted" if status == "no_material_change" else None),
            "detail_json": _json(details),
        }
        return self._write(operation_id, values)

    def freeze_scope_denominator(self, operation_id: str, denominator: Mapping[str, Any]) -> dict[str, Any]:
        """Keep the exact required run obligations in the existing lifecycle row."""
        row = self.get(operation_id)
        if row is None or row["status"] != "running":
            raise ValueError("required scopes may be frozen only for a registered running operation")
        detail = dict(row.get("detail") or {})
        prior = detail.get("required_scope_denominator")
        if prior is not None and prior != dict(denominator):
            raise ValueError("one operation cannot change its frozen required denominator")
        detail["required_scope_denominator"] = dict(denominator)
        detail.setdefault("scope_results", {})
        return self._write(operation_id, {"detail_json": _json(detail)}, insert_if_missing=False)

    def record_scope_result(self, operation_id: str, scope_id: str, result: Mapping[str, Any]) -> dict[str, Any]:
        row = self.get(operation_id)
        if row is None:
            raise KeyError(operation_id)
        detail = dict(row.get("detail") or {})
        denominator = detail.get("required_scope_denominator") or {}
        allowed = {item["scope_id"] for item in denominator.get("required_scopes", [])}
        if scope_id not in allowed:
            raise ValueError("scope result does not belong to the frozen denominator")
        results = dict(detail.get("scope_results") or {})
        if scope_id in results and results[scope_id] != dict(result):
            raise ValueError("completed scope result is immutable")
        results[scope_id] = dict(result)
        detail["scope_results"] = results
        return self._write(operation_id, {"detail_json": _json(detail)}, insert_if_missing=False)

    def get(self, operation_id: str, *, include_internal: bool = False) -> dict[str, Any] | None:
        if not self.database_path.is_file():
            return None
        with closing(sqlite3.connect(f"file:{self.database_path.resolve().as_posix()}?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            try:
                row = connection.execute("SELECT * FROM fr_product_operation_lifecycle WHERE operation_id=?", (operation_id,)).fetchone()
            except sqlite3.OperationalError:
                return None
        if not row:
            return None
        value = self._public_row(dict(row))
        if include_internal:
            value["_runtime_root"] = dict(row).get("runtime_root")
        return value

    def list(self, *, scope: str | None = None, limit: int = 20, include_internal: bool = False) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        if not self.database_path.is_file():
            return []
        with closing(sqlite3.connect(f"file:{self.database_path.resolve().as_posix()}?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            try:
                if scope:
                    rows = connection.execute("SELECT * FROM fr_product_operation_lifecycle WHERE scope=? ORDER BY revision DESC LIMIT ?", (scope, limit)).fetchall()
                else:
                    rows = connection.execute("SELECT * FROM fr_product_operation_lifecycle ORDER BY revision DESC LIMIT ?", (limit,)).fetchall()
            except sqlite3.OperationalError:
                return []
        result = []
        for row in rows:
            value = self._public_row(dict(row))
            if include_internal:
                value["_runtime_root"] = dict(row).get("runtime_root")
            result.append(value)
        return result

    def latest_configured_update(self) -> dict[str, Any] | None:
        if not self.database_path.is_file():
            return None
        with closing(sqlite3.connect(f"file:{self.database_path.resolve().as_posix()}?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            try:
                row = connection.execute(
                    "SELECT * FROM fr_product_operation_lifecycle "
                    "WHERE operation_type='configured_update' ORDER BY revision DESC LIMIT 1"
                ).fetchone()
            except sqlite3.OperationalError as exc:
                if "no such table" in str(exc).lower():
                    return None
                raise
        return self._public_row(dict(row)) if row else None

    def revision(self) -> int:
        if not self.database_path.is_file():
            return 0
        with closing(sqlite3.connect(f"file:{self.database_path.resolve().as_posix()}?mode=ro", uri=True)) as connection:
            try:
                row = connection.execute("SELECT COALESCE(MAX(revision),0) FROM fr_product_operation_lifecycle").fetchone()
            except sqlite3.OperationalError:
                return 0
        return int(row[0])

    def latest_successful_scope_checks(self) -> dict[str, dict[str, Any]]:
        """Read completed checks from immutable per-operation scope receipts.

        This is an index over the existing operation history, not a second
        freshness authority.  A failed later operation cannot erase a prior
        successful check for the same financial scope.
        """
        if not self.database_path.is_file():
            return {}
        checks: dict[str, dict[str, Any]] = {}
        with closing(sqlite3.connect(f"file:{self.database_path.resolve().as_posix()}?mode=ro", uri=True)) as connection:
            try:
                rows = connection.execute(
                    "SELECT operation_id,detail_json FROM fr_product_operation_lifecycle "
                    "WHERE operation_type='configured_update' ORDER BY revision DESC"
                )
                for operation_id, raw_detail in rows:
                    detail = json.loads(raw_detail or "{}")
                    for scope_id, result in (detail.get("scope_results") or {}).items():
                        if scope_id in checks or result.get("result") != "successful_check":
                            continue
                        if not result.get("checked_at_utc") or not result.get("check_date"):
                            continue
                        # A completed source check that found material change
                        # cannot represent the serving dataset's check date
                        # until that operation's immutable successor is
                        # durably published.  No-change checks can stand on
                        # their own because the active facts remain current.
                        if result.get("material_change") and _publication_transition_for_operation(
                            self.database_path, str(operation_id)
                        ) is None:
                            continue
                        checks[scope_id] = {
                            "status": "available", "value": result["check_date"],
                            "checked_at_utc": result["checked_at_utc"],
                            "operation_id": operation_id,
                            "material_change": bool(result.get("material_change")),
                            "scope": scope_id,
                            "basis": "completed_required_scope_check_receipt",
                        }
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc).lower():
                    raise
        return checks

    @staticmethod
    def _public_row(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "operation_id": row["operation_id"],
            "operation_type": row["operation_type"],
            "scope": row["scope"],
            "status": row["status"],
            "outcome_code": row.get("outcome_code"),
            "reason_code": row.get("reason_code"),
            "error_class": row.get("error_class"),
            "retryable": bool(row.get("retryable")),
            "recoverable": bool(row.get("recoverable")),
            "serving_unchanged": None if row.get("serving_unchanged") is None else bool(row.get("serving_unchanged")),
            "started_at_utc": row.get("started_at_utc"),
            "updated_at_utc": row.get("updated_at_utc"),
            "completed_at_utc": row.get("completed_at_utc"),
            "predecessor_release_id": row.get("predecessor_release_id"),
            "predecessor_snapshot_id": row.get("predecessor_snapshot_id"),
            "successor_release_id": row.get("successor_release_id"),
            "successor_snapshot_id": row.get("successor_snapshot_id"),
            "active_release_id": row.get("active_release_id"),
            "active_release_hash": row.get("active_release_hash"),
            "active_snapshot_id": row.get("active_snapshot_id"),
            "changed_component": row.get("changed_component"),
            "publication_status": row.get("publication_status"),
            "revision": int(row.get("revision") or 0),
            "detail": redact_value(json.loads(row.get("detail_json") or "{}")),
        }


def lifecycle_read_model(
    *,
    scope: str | None = None,
    limit: int = 20,
    bound_snapshot_id: str | None = None,
    bound_release_id: str | None = None,
    operation_id: str | None = None,
) -> dict[str, Any]:
    if scope is not None and scope not in SCOPES:
        raise ValueError(f"unsupported operation scope: {scope}")
    store = OperationLifecycleStore()
    active = active_serving_view()
    rows = [store.get(operation_id, include_internal=True)] if operation_id else store.list(scope=scope, limit=limit, include_internal=True)
    rows = [_effective_row(row, active, database_path=store.database_path) for row in rows if row is not None]
    for row in rows:
        row.pop("_runtime_root", None)
    component_views = {name: _component_view(active, name) for name in ("Fund", "Equity")}
    binding: dict[str, Any] | None = None
    if bound_snapshot_id or bound_release_id:
        if bound_release_id:
            current = active.get("release_id")
            binding = {
                "basis": "release_id",
                "bound_release_id": bound_release_id,
                "current_release_id": current,
                "is_current": bool(current and current == bound_release_id),
                "active_binding_differs": bool(current and current != bound_release_id),
            }
        else:
            if scope in COMPONENT_BY_SCOPE:
                current_component = component_views[scope]
                binding = {
                    "basis": "component_snapshot_id",
                    "bound_snapshot_id": bound_snapshot_id,
                    "scope": scope,
                    "current_component_snapshot_id": current_component.get("snapshot_id"),
                    "is_current": bool(current_component.get("snapshot_id") == bound_snapshot_id),
                    "active_binding_differs": bool(current_component.get("snapshot_id") and current_component.get("snapshot_id") != bound_snapshot_id),
                }
            else:
                current_snapshot = active.get("snapshot_id")
                binding = {
                    "basis": "composite_snapshot_id",
                    "bound_snapshot_id": bound_snapshot_id,
                    "scope": None,
                    "current_snapshot_id": current_snapshot,
                    "is_current": bool(current_snapshot and current_snapshot == bound_snapshot_id),
                    "active_binding_differs": bool(current_snapshot and current_snapshot != bound_snapshot_id),
                }
    latest_by_scope: dict[str, dict[str, Any] | None] = {}
    for candidate_scope in ("installation", "Fund", "Equity"):
        latest = store.list(scope=candidate_scope, limit=1, include_internal=True)
        projected = _effective_row(latest[0], active, database_path=store.database_path) if latest else None
        if projected:
            projected.pop("_runtime_root", None)
        latest_by_scope[candidate_scope] = projected
    freshness_by_scope: dict[str, dict[str, Any]] = {}
    successful_checks = store.latest_successful_scope_checks()
    from backend.app.core.update_scope_contract import SUPPORTED_SCOPE_ROUTES
    from backend.app.core.desired_data_profile import DesiredDataProfileRepository
    from backend.app.core.update_scope_contract import freeze_required_update_scopes
    try:
        current_configuration = DesiredDataProfileRepository(store.database_path).current_configuration()
        configured_scope_ids = {
            item["scope_id"] for item in freeze_required_update_scopes(current_configuration)["required_scopes"]
        }
    except (ValueError, KeyError, OSError, sqlite3.Error):
        configured_scope_ids = set()
    recent_configured = store.latest_configured_update()
    latest_scope_results = dict((recent_configured or {}).get("detail", {}).get("scope_results") or {})
    for candidate_scope in ("Fund", "Equity"):
        component = component_views[candidate_scope]
        component_snapshot = component.get("snapshot_id")
        published = next((
            row for row in store.list(scope=candidate_scope, limit=100)
            if row.get("status") == "published"
            and row.get("publication_status") in {"published", "already_active"}
            and row.get("successor_snapshot_id") == component_snapshot
            and component_snapshot
        ), None)
        freshness_by_scope[candidate_scope] = {
            "scope": "active_serving_component",
            "component_id": component.get("component_id"),
            "component_snapshot_id": component_snapshot,
            "latest_observation": {
                "value": None, "status": "not_proven", "scope": "universe_aggregate",
                "reason": "no_release_bound_aggregate_observation_watermark",
            },
            "last_checked": (successful_checks["fund.china.public"] if candidate_scope == "Fund"
                             and "fund.china.public" in successful_checks else {
                "value": None, "status": "not_proven", "scope": "source_check",
                "reason": "component_aggregate_or_required_scope_check_not_proven",
            }),
            "last_updated": {
                "value": published.get("completed_at_utc") if published else None,
                "status": "available" if published else "not_proven",
                "scope": "active_serving_component",
                "basis": "completed_published_update_for_current_component" if published else None,
                "operation_id": published.get("operation_id") if published else None,
            },
            "availability": {
                "status": "available" if component.get("queryable") else "unavailable",
                "scope": "active_serving_component_binding",
                "basis": "active_pointer_component_binding_only",
                "does_not_imply_series_coverage": True,
            },
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": store.revision(),
        "observed_at_utc": _now(),
        "active_serving": active,
        "serving_by_scope": component_views,
        "serving_by_universe": component_views,  # v1 response compatibility
        "latest_by_scope": latest_by_scope,
        "freshness_by_scope": freshness_by_scope,
        "freshness_by_update_scope": {
            scope_id: {
                "currently_configured": scope_id in configured_scope_ids,
                "last_checked": successful_checks.get(scope_id) or {
                    "value": None, "status": "not_proven", "scope": scope_id,
                    "reason": "no_completed_required_scope_check_receipt",
                },
                "latest_run_result": latest_scope_results.get(scope_id),
                "latest_operation_id": recent_configured.get("operation_id") if recent_configured else None,
            }
            for scope_id in (str(route["scope_id"]) for route in SUPPORTED_SCOPE_ROUTES)
        },
        "operations": rows,
        "binding": binding,
    }


def record_operation_started(
    operation_id: str,
    *,
    operation_type: str,
    scope: str,
    predecessor: Mapping[str, Any] | None = None,
    runtime_root: Path | str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    try:
        return OperationLifecycleStore().begin(
            operation_id,
            operation_type=operation_type,
            scope=scope,
            predecessor=predecessor,
            runtime_root=runtime_root,
            request_id=request_id,
        )
    except Exception as exc:
        raise OperationRegistrationUnavailable(
            f"operation registration unavailable for {operation_type}/{scope}"
        ) from exc


def record_operation_result(operation_id: str, result: Mapping[str, Any], *, operation_type: str, scope: str) -> dict[str, Any]:
    return OperationLifecycleStore().transition(operation_id, result, operation_type=operation_type, scope=scope)
