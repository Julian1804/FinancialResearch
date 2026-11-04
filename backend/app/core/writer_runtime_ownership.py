"""Installation-local writer ownership and conservative runtime classification.

The validated-head and active-pointer CAS operations remain the authority for
durable state.  This module adds the missing *whole workflow* exclusion: one
installation writer owns update, validation, and publication at a time.  The
lease is persisted in the control database so separate processes share the
same contract.  A lease is reclaimable only when its recorded owner process is
provably dead; elapsed time alone never authorizes takeover.

Runtime markers are descriptive only.  Classification never deletes files and
requires explicit evidence before calling work reusable or cleanup-eligible.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import closing
import threading
import uuid
from contextlib import AbstractContextManager
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.app.core.artifact_io import write_json_atomic
from backend.app.core.storage_profile import resolve_control_plane_path


LEASE_SCHEMA = "fr_installation_writer_lease_v1"
RUNTIME_MARKER_SCHEMA = "fr_runtime_owner_marker_v1"
PROCESS_INSTANCE_ID = uuid.uuid4().hex


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


PROCESS_START_UTC = _now()


def _pid_alive(pid: int | None) -> bool:
    """Return a conservative process-liveness answer.

    Permission errors are treated as alive/unknown.  We must never reclaim a
    lease merely because the host refused to answer the liveness probe.
    """

    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        # ``os.kill(pid, 0)`` is not a reliable termination probe on Windows:
        # it can continue to succeed for a PID whose process has already
        # exited.  Query the process exit code and treat access denial as
        # alive/unknown so cleanup and takeover remain conservative.
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        kernel32.GetExitCodeProcess.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, int(pid))
        if not handle:
            error = ctypes.get_last_error()
            if error in {5, 1314}:  # access denied / privilege not held
                return True
            return False
        try:
            exit_code = ctypes.c_uint32()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        # Windows reports a handful of invalid-handle/process-not-found
        # conditions as generic OSError rather than ProcessLookupError.
        if getattr(exc, "winerror", None) in {3, 6, 87, 128}:
            return False
        return True
    return True


def process_identity() -> dict[str, Any]:
    """Return the interpreter instance identity persisted with owned work."""

    return {
        "pid": os.getpid(),
        "process_instance_id": PROCESS_INSTANCE_ID,
        "process_start_utc": PROCESS_START_UTC,
    }


def _owner_liveness(pid: int, process_instance_id: str | None) -> str:
    """Classify owner liveness without treating PID as unique forever.

    A live PID from another process is sufficient to protect the lease, but a
    same-PID/different-instance observation is explicitly ambiguous (PID reuse
    or a legacy row) and is also protected.  Only a definitively absent PID is
    reclaimable.
    """

    if not _pid_alive(pid):
        return "dead"
    if pid == os.getpid() and process_instance_id not in {None, PROCESS_INSTANCE_ID, "legacy-unknown"}:
        return "ambiguous"
    return "alive"


@dataclass(frozen=True)
class WriterLeaseRecord:
    owner_id: str
    operation_id: str
    pid: int
    process_instance_id: str
    process_start_utc: str | None
    acquired_at_utc: str
    heartbeat_at_utc: str
    lease_expires_at_utc: str
    status: str = "active"
    previous_owner_id: str | None = None


class WriterBusyError(RuntimeError):
    """Another live process owns the installation writer lease."""

    def __init__(self, record: WriterLeaseRecord):
        self.record = record
        super().__init__(
            f"installation writer is busy: owner={record.owner_id} "
            f"operation={record.operation_id} pid={record.pid}"
        )


class WriterLeaseLost(RuntimeError):
    """The current process no longer owns the persisted lease."""


class InstallationWriterLease(AbstractContextManager["InstallationWriterLease"]):
    """Cross-process, installation-scoped writer lease.

    ``lease_seconds`` is a heartbeat/recovery hint, not a deletion or takeover
    rule.  A live owner remains authoritative even after the hint expires.
    """

    def __init__(
        self,
        *,
        database_path: Path | None = None,
        operation_id: str,
        owner_id: str | None = None,
        lease_seconds: int = 60,
    ) -> None:
        self.database_path = Path(database_path) if database_path else resolve_control_plane_path()
        self.operation_id = operation_id
        self.owner_id = owner_id or f"writer-{uuid.uuid4().hex}"
        self.lease_seconds = max(int(lease_seconds), 1)
        self.record: WriterLeaseRecord | None = None
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_failure: Exception | None = None

    @staticmethod
    def _schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS fr_installation_writer_lease(
                singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),
                owner_id TEXT NOT NULL,
                operation_id TEXT NOT NULL,
                pid INTEGER NOT NULL,
                process_instance_id TEXT NOT NULL,
                process_start_utc TEXT,
                acquired_at_utc TEXT NOT NULL,
                heartbeat_at_utc TEXT NOT NULL,
                lease_expires_at_utc TEXT NOT NULL,
                status TEXT NOT NULL,
                previous_owner_id TEXT
            )"""
        )
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(fr_installation_writer_lease)")}
        if "process_instance_id" not in columns:
            connection.execute("ALTER TABLE fr_installation_writer_lease ADD COLUMN process_instance_id TEXT NOT NULL DEFAULT 'legacy-unknown'")
        if "process_start_utc" not in columns:
            connection.execute("ALTER TABLE fr_installation_writer_lease ADD COLUMN process_start_utc TEXT")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS fr_installation_writer_lease_history(
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                operation_id TEXT NOT NULL,
                pid INTEGER NOT NULL,
                event_at_utc TEXT NOT NULL,
                previous_owner_id TEXT,
                detail_json TEXT NOT NULL
            )"""
        )

    def _expires(self) -> str:
        # A monotonic deadline cannot be shared across processes.  The stored
        # timestamp is diagnostic only; owner liveness is the takeover proof.
        from datetime import timedelta

        return (datetime.now(timezone.utc) + timedelta(seconds=self.lease_seconds)).isoformat().replace("+00:00", "Z")

    def acquire(self) -> "InstallationWriterLease":
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        now = _now()
        try:
            connection = sqlite3.connect(self.database_path, timeout=0.5)
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower():
                raise
            # A competing process is between lease acquisition and commit.
            # Read its durable row after the short lock wait and report busy;
            # never spin or treat SQLite lock timeout as takeover evidence.
            with closing(sqlite3.connect(self.database_path, timeout=5)) as read_connection:
                row = read_connection.execute(
                    "SELECT owner_id,operation_id,pid,process_instance_id,process_start_utc,acquired_at_utc,heartbeat_at_utc,lease_expires_at_utc,status,previous_owner_id FROM fr_installation_writer_lease WHERE singleton_id=1"
                ).fetchone()
            if row:
                raise WriterBusyError(WriterLeaseRecord(*row)) from exc
            raise
        try:
            self._schema(connection)
            row = connection.execute(
                "SELECT owner_id,operation_id,pid,process_instance_id,process_start_utc,acquired_at_utc,heartbeat_at_utc,lease_expires_at_utc,status,previous_owner_id "
                "FROM fr_installation_writer_lease WHERE singleton_id=1"
            ).fetchone()
            previous_owner: str | None = None
            if row:
                existing = WriterLeaseRecord(*row)
                liveness = _owner_liveness(existing.pid, existing.process_instance_id)
                same_process_owner = (
                    existing.owner_id == self.owner_id
                    and existing.pid == os.getpid()
                    and existing.process_instance_id == PROCESS_INSTANCE_ID
                )
                if not same_process_owner and liveness != "dead":
                    connection.rollback()
                    raise WriterBusyError(existing)
                previous_owner = existing.owner_id
                connection.execute("DELETE FROM fr_installation_writer_lease WHERE singleton_id=1")
                connection.execute(
                    "INSERT INTO fr_installation_writer_lease_history(event_type,owner_id,operation_id,pid,event_at_utc,previous_owner_id,detail_json) VALUES(?,?,?,?,?,?,?)",
                    ("takeover_after_owner_dead", self.owner_id, self.operation_id, os.getpid(), now, previous_owner, json.dumps({**asdict(existing), "liveness": liveness}, sort_keys=True)),
                )
            record = WriterLeaseRecord(
                owner_id=self.owner_id,
                operation_id=self.operation_id,
                pid=os.getpid(),
                process_instance_id=PROCESS_INSTANCE_ID,
                process_start_utc=PROCESS_START_UTC,
                acquired_at_utc=now,
                heartbeat_at_utc=now,
                lease_expires_at_utc=self._expires(),
                previous_owner_id=previous_owner,
            )
            connection.execute(
                "INSERT INTO fr_installation_writer_lease(singleton_id,owner_id,operation_id,pid,process_instance_id,process_start_utc,acquired_at_utc,heartbeat_at_utc,lease_expires_at_utc,status,previous_owner_id) VALUES(1,?,?,?,?,?,?,?,?,?,?)",
                (record.owner_id, record.operation_id, record.pid, record.process_instance_id, record.process_start_utc, record.acquired_at_utc, record.heartbeat_at_utc, record.lease_expires_at_utc, record.status, record.previous_owner_id),
            )
            connection.execute(
                "INSERT INTO fr_installation_writer_lease_history(event_type,owner_id,operation_id,pid,event_at_utc,previous_owner_id,detail_json) VALUES(?,?,?,?,?,?,?)",
                ("acquired", record.owner_id, record.operation_id, record.pid, now, previous_owner, json.dumps(asdict(record), sort_keys=True)),
            )
            connection.commit()
        finally:
            connection.close()
        self.record = record
        self.start_heartbeat()
        return self

    def heartbeat(self) -> WriterLeaseRecord:
        if self.record is None:
            raise WriterLeaseLost("writer lease is not acquired")
        now = _now()
        # Keep the keepalive bounded so release/cleanup cannot be held hostage
        # by a competing SQLite writer transaction.
        connection = sqlite3.connect(self.database_path, timeout=1)
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE fr_installation_writer_lease SET heartbeat_at_utc=?,lease_expires_at_utc=? WHERE singleton_id=1 AND owner_id=? AND operation_id=? AND pid=? AND process_instance_id=? AND status='active'",
                (now, self._expires(), self.record.owner_id, self.record.operation_id, self.record.pid, self.record.process_instance_id),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise WriterLeaseLost("writer lease ownership changed")
            connection.commit()
        finally:
            connection.close()
        self.record = WriterLeaseRecord(**{**asdict(self.record), "heartbeat_at_utc": now, "lease_expires_at_utc": self._expires()})
        return self.record

    def start_heartbeat(self) -> None:
        """Continuously renew the owned lease during synchronous work.

        Lease expiry is diagnostic and never authorizes takeover by itself;
        this keepalive nevertheless keeps the durable ownership record current
        while a provider/build/publication stage is running for longer than the
        nominal lease interval.
        """
        if self.record is None or (self._heartbeat_thread and self._heartbeat_thread.is_alive()):
            return
        self._heartbeat_stop.clear()
        interval = max(0.25, min(self.lease_seconds / 3.0, 10.0))

        def renew() -> None:
            while not self._heartbeat_stop.wait(interval):
                try:
                    self.heartbeat()
                except Exception as exc:  # pragma: no cover - exercised through ownership readback
                    self._heartbeat_failure = exc
                    return

        self._heartbeat_thread = threading.Thread(
            target=renew,
            name=f"fr-writer-lease-heartbeat-{self.operation_id}",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        thread = self._heartbeat_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=max(2.0, min(self.lease_seconds * 2.0, 10.0)))
        self._heartbeat_thread = None

    def release(self, *, status: str = "released") -> None:
        self.stop_heartbeat()
        if self.record is None:
            return
        now = _now()
        connection = sqlite3.connect(self.database_path, timeout=30)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT owner_id,operation_id,pid,process_instance_id FROM fr_installation_writer_lease WHERE singleton_id=1").fetchone()
            if row and tuple(row) != (self.record.owner_id, self.record.operation_id, self.record.pid, self.record.process_instance_id):
                connection.rollback()
                raise WriterLeaseLost("writer lease ownership changed before release")
            if row:
                connection.execute("DELETE FROM fr_installation_writer_lease WHERE singleton_id=1")
                connection.execute(
                    "INSERT INTO fr_installation_writer_lease_history(event_type,owner_id,operation_id,pid,event_at_utc,previous_owner_id,detail_json) VALUES(?,?,?,?,?,?,?)",
                    (status, self.record.owner_id, self.record.operation_id, self.record.pid, now, self.record.previous_owner_id, json.dumps(asdict(self.record), sort_keys=True)),
                )
            connection.commit()
        finally:
            connection.close()
        self.record = WriterLeaseRecord(**{**asdict(self.record), "status": status})

    def __enter__(self) -> "InstallationWriterLease":
        return self.acquire()

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.release(status="failed" if exc else "released")


def acquire_writer_lease(*, operation_id: str, database_path: Path | None = None, lease_seconds: int = 60) -> InstallationWriterLease:
    return InstallationWriterLease(database_path=database_path, operation_id=operation_id, lease_seconds=lease_seconds).acquire()


def write_runtime_owner_marker(
    run_root: Path,
    *,
    operation_id: str,
    owner_id: str,
    predecessor_snapshot_id: str | None,
    state: str = "active",
    successor_snapshot_id: str | None = None,
    checkpoint_verified: bool = False,
    recovery_contract: Mapping[str, Any] | None = None,
) -> Path:
    if state not in {"active", "completed", "failed", "interrupted"}:
        raise ValueError("unsupported runtime owner state")
    path = run_root / "runtime_owner_v1.json"
    payload = {
        "schema_version": RUNTIME_MARKER_SCHEMA,
        "operation_id": operation_id,
        "owner_id": owner_id,
        "pid": os.getpid(),
        "process_instance_id": PROCESS_INSTANCE_ID,
        "process_start_utc": PROCESS_START_UTC,
        "created_at_utc": _now(),
        "updated_at_utc": _now(),
        "heartbeat_at_utc": _now(),
        "state": state,
        "predecessor_snapshot_id": predecessor_snapshot_id,
        "successor_snapshot_id": successor_snapshot_id,
        "checkpoint_verified": bool(checkpoint_verified),
    }
    if recovery_contract is not None:
        payload["recovery_contract"] = dict(recovery_contract)
    elif path.is_file():
        prior = json.loads(path.read_text(encoding="utf-8"))
        if "recovery_contract" in prior:
            payload["recovery_contract"] = prior["recovery_contract"]
        payload["created_at_utc"] = prior.get("created_at_utc", payload["created_at_utc"])
    write_json_atomic(path, payload)
    return path


def inspect_fund_recovery_candidate(
    run_root: Path,
    *,
    start_date: str | None,
    completed_through: str | None,
) -> dict[str, Any]:
    """Mirror the accepted Fund staged-recovery admission predicate.

    This is deliberately neutral filesystem logic.  The Fund recovery owner
    calls it for candidate selection, and runtime classification calls it to
    prevent disposal of a checkpoint that the owner can reuse.
    """

    checkpoint_path = run_root / "acquisition_checkpoint_v1.json"
    result_path = run_root / "result_v1.json"
    stage = run_root / "staged_increment"
    if result_path.exists():
        return {"status": "not_recoverable", "reason": "final_result_exists", "run_root": str(run_root)}
    if not checkpoint_path.is_file():
        return {"status": "unknown", "reason": "checkpoint_missing", "run_root": str(run_root)}
    if not stage.is_dir():
        return {"status": "unknown", "reason": "staged_increment_missing", "run_root": str(run_root)}
    try:
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "unknown", "reason": f"checkpoint_unreadable:{type(exc).__name__}", "run_root": str(run_root)}
    staged_dates = sorted(
        match.group(1)
        for path in stage.rglob("*.parquet")
        if (match := re.search(r"update_run=[^/\\]*?(\d{4}-\d{2}-\d{2})", path.as_posix()))
    )
    if not staged_dates or not start_date or not completed_through:
        return {"status": "unknown", "reason": "recovery_window_inputs_missing", "staged_dates": staged_dates, "run_root": str(run_root)}
    try:
        first_date = datetime.strptime(staged_dates[0], "%Y-%m-%d").date()
        logical_start = datetime.strptime(start_date, "%Y-%m-%d").date()
    except ValueError:
        return {"status": "unknown", "reason": "invalid_recovery_date", "staged_dates": staged_dates, "run_root": str(run_root)}
    same_window = logical_start <= first_date <= logical_start + timedelta(days=2)
    matches = checkpoint.get("last_completed_date") == completed_through
    if same_window and matches:
        return {
            "status": "reusable",
            "reason": "accepted_fund_recovery_predicate",
            "checkpoint_path": str(checkpoint_path),
            "staged_root": str(stage),
            "staged_dates": staged_dates,
            "last_completed_date": checkpoint.get("last_completed_date"),
            "run_root": str(run_root),
        }
    return {
        "status": "not_recoverable",
        "reason": "recovery_window_mismatch",
        "staged_dates": staged_dates,
        "last_completed_date": checkpoint.get("last_completed_date"),
        "run_root": str(run_root),
    }


def classify_runtime_artifact(
    run_root: Path,
    *,
    active_snapshot_id: str | None = None,
    retained_snapshot_ids: set[str] | None = None,
    now_utc: str | None = None,
) -> dict[str, Any]:
    """Classify one run without deleting or mutating it."""

    marker_path = run_root / "runtime_owner_v1.json"
    if not marker_path.is_file():
        return {"classification": "unknown", "cleanup_eligible": False, "reason": "owner_marker_missing", "path": str(run_root)}
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    state = str(marker.get("state") or "unknown")
    owner_liveness = _owner_liveness(int(marker.get("pid") or 0), marker.get("process_instance_id")) if state == "active" else "not_active"
    owner_alive = owner_liveness == "alive"
    successor = marker.get("successor_snapshot_id")
    checkpoint_verified = bool(marker.get("checkpoint_verified"))
    retained = retained_snapshot_ids or set()
    recovery_contract = marker.get("recovery_contract") or {}
    recovery = {"status": "unknown", "reason": "recovery_contract_missing"}
    if recovery_contract.get("kind") == "china_public_fund_increment":
        recovery = inspect_fund_recovery_candidate(
            run_root,
            start_date=recovery_contract.get("logical_window_start"),
            completed_through=recovery_contract.get("completed_through"),
        )
    elif recovery_contract.get("recovery_reusable") is False:
        recovery = {"status": "not_recoverable", "reason": "explicit_no_recovery_contract"}
    # A checkpoint plus staged increment is itself a recovery obligation.  A
    # marker is allowed to say that disposal is safe only when the recovery
    # owner has independently established that no resumable work remains.
    # Keep an unfinalized candidate protected when its recovery window cannot
    # be reconstructed from the marker; cleanup must never outrun recovery.
    unfinalized_staged_work = (
        (run_root / "acquisition_checkpoint_v1.json").is_file()
        and (run_root / "staged_increment").is_dir()
        and not (run_root / "result_v1.json").exists()
    )
    if state == "active" and owner_liveness == "alive":
        classification, reason = "active", "owner_process_alive"
    elif state == "active" and owner_liveness == "ambiguous":
        classification, reason = "unknown", "owner_process_identity_ambiguous"
    elif recovery.get("status") == "reusable":
        classification, reason = "reusable", "accepted_recovery_contract"
    elif successor and checkpoint_verified and active_snapshot_id and successor == active_snapshot_id:
        classification, reason = "reusable", "successor_is_active_snapshot"
    elif successor and checkpoint_verified and successor in retained:
        classification, reason = "reusable", "successor_is_retained"
    elif (
        successor
        and checkpoint_verified
        and active_snapshot_id is not None
        and recovery_contract.get("post_publication_disposable") is True
    ):
        # A published successor's runtime work is not itself part of the
        # immutable release.  Once the successor is no longer the active
        # component and no explicit retained runtime dependency names it,
        # the owner marker proves that recovery/publication work is over.
        # Keep the active and explicitly retained cases above protected.
        classification, reason = "stale", "published_successor_has_no_retained_runtime_dependency"
    elif successor and checkpoint_verified and active_snapshot_id and successor != active_snapshot_id:
        classification, reason = "superseded", "a different snapshot is active"
    elif unfinalized_staged_work:
        classification, reason = "unknown", "unfinalized_staged_work_requires_recovery_review"
    elif recovery.get("status") == "unknown":
        classification, reason = "unknown", str(recovery.get("reason") or "recovery_state_unknown")
    elif state in {"completed", "failed", "interrupted"} or (state == "active" and not owner_alive):
        classification, reason = "stale", "owner_finished_or_process_dead"
    else:
        classification, reason = "unknown", "insufficient_ownership_evidence"
    cleanup = bool(
        classification in {"stale", "reusable"}
        and (
            not successor
            or (
                recovery_contract.get("post_publication_disposable") is True
                and active_snapshot_id is not None
                and successor != active_snapshot_id
                and successor not in retained
            )
        )
        and recovery.get("status") == "not_recoverable"
        and recovery_contract.get("disposal_proof") is True
        and recovery_contract.get("protected_dependencies") == []
        and recovery_contract.get("publication_obligation") is False
        and recovery_contract.get("identity_obligation") is False
    )
    return {
        "path": str(run_root),
        "classification": classification,
        "cleanup_eligible": cleanup,
        "reason": reason,
        "owner_id": marker.get("owner_id"),
        "owner_liveness": owner_liveness,
        "owner_process_instance_id": marker.get("process_instance_id"),
        "operation_id": marker.get("operation_id"),
        "pid": marker.get("pid"),
        "successor_snapshot_id": successor,
        "checkpoint_verified": checkpoint_verified,
        "active_snapshot_id": active_snapshot_id,
        "retained_snapshot_ids": sorted(retained),
        "recovery": recovery,
        "deletion_performed": False,
        "observed_at_utc": now_utc or _now(),
    }

