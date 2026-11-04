"""Immutable checkpoint-plus-delta control state for database successors.

Complete historical control SQLite files remain readable checkpoints.  A
successor control file contains only locally changed rows and a hash-bound
reference to its immutable predecessor.  Readers overlay indexed rows from
newest to oldest; they never flatten the chain as part of an ordinary update.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from backend.app.core.artifact_io import canonical_json, sha256_file


CONTROL_DELTA_SCHEMA = "fr_incremental_control_delta_v1"


class IncrementalControlError(RuntimeError):
    pass


class IncrementalControlSearchLimit(IncrementalControlError):
    """Complete discovery would exceed its measured in-memory row budget."""


@dataclass(frozen=True)
class ControlLayer:
    snapshot_id: str
    control_path: Path
    manifest_path: Path
    is_checkpoint: bool


def ensure_control_watermark_schema(connection: sqlite3.Connection) -> None:
    """Add bounded read accelerators without turning a checkpoint into a delta."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS control_series_watermark(
          subject_type TEXT NOT NULL,
          subject_id TEXT NOT NULL,
          metric_id TEXT NOT NULL,
          time_end TEXT NOT NULL,
          PRIMARY KEY(subject_type,subject_id,metric_id)
        );
        CREATE TABLE IF NOT EXISTS control_watermark_state(
          singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),
          complete_checkpoint INTEGER NOT NULL CHECK(complete_checkpoint IN (0,1))
        );
        """
    )


def ensure_delta_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS control_delta_metadata(
          singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),
          schema_version TEXT NOT NULL,
          snapshot_id TEXT NOT NULL,
          predecessor_snapshot_id TEXT NOT NULL,
          predecessor_manifest_sha256 TEXT NOT NULL,
          predecessor_control_sha256 TEXT NOT NULL,
          base_checkpoint_snapshot_id TEXT NOT NULL,
          created_at_utc TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS control_record_tombstone(
          record_kind TEXT NOT NULL,
          record_key TEXT NOT NULL,
          reason TEXT NOT NULL,
          created_at_utc TEXT NOT NULL,
          PRIMARY KEY(record_kind,record_key)
        );
        CREATE TABLE IF NOT EXISTS control_subject_override(
          record_kind TEXT NOT NULL,
          subject_type TEXT NOT NULL,
          subject_id TEXT NOT NULL,
          created_at_utc TEXT NOT NULL,
          PRIMARY KEY(record_kind,subject_type,subject_id)
        );
        CREATE TABLE IF NOT EXISTS control_series_watermark(
          subject_type TEXT NOT NULL,
          subject_id TEXT NOT NULL,
          metric_id TEXT NOT NULL,
          time_end TEXT NOT NULL,
          PRIMARY KEY(subject_type,subject_id,metric_id)
        );
        CREATE TABLE IF NOT EXISTS control_watermark_state(
          singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),
          complete_checkpoint INTEGER NOT NULL CHECK(complete_checkpoint IN (0,1))
        );
        """
    )


def initialize_delta(
    connection: sqlite3.Connection,
    *,
    snapshot_id: str,
    predecessor_snapshot_id: str,
    predecessor_manifest_sha256: str,
    predecessor_control_sha256: str,
    base_checkpoint_snapshot_id: str,
    created_at_utc: str,
) -> None:
    ensure_delta_schema(connection)
    connection.execute(
        "INSERT INTO control_delta_metadata VALUES (1,?,?,?,?,?,?,?)",
        (
            CONTROL_DELTA_SCHEMA,
            snapshot_id,
            predecessor_snapshot_id,
            predecessor_manifest_sha256,
            predecessor_control_sha256,
            base_checkpoint_snapshot_id,
            created_at_utc,
        ),
    )


def control_member_hash(manifest_path: Path, relative_path: str) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    matches = [
        row for row in manifest.get("files", [])
        if row.get("relative_path") == relative_path
    ]
    if len(matches) != 1:
        raise IncrementalControlError("manifest has no unique control member")
    return str(matches[0]["content_sha256"])


@lru_cache(maxsize=256)
def _verified_file_sha256(path_text: str, size: int, mtime_ns: int) -> str:
    """Hash one immutable control member once per observed physical identity."""
    del size, mtime_ns
    return sha256_file(Path(path_text))


def _control_receipt_binds(
    manifest_path: Path, control_path: Path, relative_path: str,
    receipt: Mapping[str, Any],
) -> bool:
    """True when the publication receipt binds this manifest member exactly.

    The receipt is accepted only when its content hash equals the immutable
    manifest member entry and the physical file size tripwire is quiet.
    Size is a corruption tripwire here, never a content proof: the content
    identity comes from the release-bound manifest chain.
    """
    if receipt.get("owner") != "snapshot_member" or receipt.get("relative_path") != relative_path:
        return False
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    matches = [row for row in manifest.get("files", []) if row.get("relative_path") == relative_path]
    if len(matches) != 1:
        return False
    member = matches[0]
    if str(member.get("content_sha256")) != str(receipt.get("content_sha256")):
        return False
    receipt_bytes = receipt.get("byte_count")
    if receipt_bytes is None:
        return False
    if member.get("byte_count") is not None and int(member["byte_count"]) != int(receipt_bytes):
        return False
    if not control_path.is_file():
        return False
    if control_path.stat().st_size != int(receipt_bytes):
        return False
    return True


def verify_manifest_control_member(
    manifest_path: Path, control_path: Path, relative_path: str,
    *, receipt: Mapping[str, Any] | None = None,
) -> str:
    """Require one control file to be the member certified by its snapshot manifest.

    When a publication receipt from the release lifecycle binds the exact
    release/manifest/member identity of this member, the receipt's
    manifest-bound content hash is returned after the physical size tripwire
    check, without re-reading the member.  A missing, unbound, or
    inconsistent receipt falls back to the full content hash and binding
    comparison, which is the exact behavior of every path without a receipt.
    """
    if receipt is not None and _control_receipt_binds(manifest_path, control_path, relative_path, receipt):
        return str(receipt["content_sha256"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    matches = [row for row in manifest.get("files", []) if row.get("relative_path") == relative_path]
    if len(matches) != 1:
        raise IncrementalControlError("manifest has no unique control member")
    member = matches[0]
    if not control_path.is_file():
        raise IncrementalControlError("manifest control member is unavailable")
    stat = control_path.stat()
    if member.get("byte_count") is not None and int(member["byte_count"]) != stat.st_size:
        raise IncrementalControlError("manifest control member size mismatch")
    actual = _verified_file_sha256(str(control_path.resolve()), stat.st_size, stat.st_mtime_ns)
    expected = str(member["content_sha256"])
    if actual != expected:
        raise IncrementalControlError("manifest control member content binding mismatch")
    return actual


def base_checkpoint_snapshot_id(control_path: Path, snapshot_id: str) -> str:
    with closing(sqlite3.connect(f"file:{control_path.as_posix()}?mode=ro", uri=True)) as connection:
        present = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='control_delta_metadata'"
        ).fetchone()
        if not present:
            return snapshot_id
        row = connection.execute(
            "SELECT base_checkpoint_snapshot_id FROM control_delta_metadata WHERE singleton_id=1"
        ).fetchone()
    if row is None:
        raise IncrementalControlError("delta control has no metadata row")
    return str(row[0])


class IncrementalControlView:
    """Read one pinned effective control state without flattening its ancestors."""

    def __init__(
        self,
        snapshot_id: str,
        *,
        control_path: Callable[[str], Path],
        manifest_path: Callable[[str], Path],
        control_relative_path: str,
        verification_receipts: Mapping[str, Mapping[str, Any]] | None = None,
    ):
        self.snapshot_id = snapshot_id
        self._control_path = control_path
        self._manifest_path = manifest_path
        self.control_relative_path = control_relative_path
        self.layers = self._load_layers(verification_receipts=verification_receipts or {})
        self.last_resolution_stats: dict[str, int] = {}
        target = json.loads(self._manifest_path(snapshot_id).read_text(encoding="utf-8"))
        if target.get("snapshot_id") != snapshot_id:
            raise IncrementalControlError("target manifest snapshot binding mismatch")
        self.target_members = {
            str(row["relative_path"]): (str(row["layer_name"]), str(row["content_sha256"]))
            for row in target.get("files", [])
        }

    def _load_layers(self, *, verification_receipts: Mapping[str, Mapping[str, Any]] | None = None) -> tuple[ControlLayer, ...]:
        verification_receipts = verification_receipts or {}
        layers: list[ControlLayer] = []
        seen: set[str] = set()
        current = self.snapshot_id
        while True:
            if current in seen:
                raise IncrementalControlError("control predecessor cycle")
            seen.add(current)
            control = self._control_path(current)
            manifest = self._manifest_path(current)
            if not control.is_file() or not manifest.is_file():
                raise IncrementalControlError(f"control ancestor is unavailable: {current}")
            manifest_value = json.loads(manifest.read_text(encoding="utf-8"))
            if manifest_value.get("snapshot_id") != current:
                raise IncrementalControlError("control manifest snapshot binding mismatch")
            verify_manifest_control_member(
                manifest, control, self.control_relative_path,
                receipt=verification_receipts.get(current),
            )
            with closing(sqlite3.connect(f"file:{control.as_posix()}?mode=ro", uri=True)) as connection:
                present = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='control_delta_metadata'"
                ).fetchone()
                if not present:
                    layers.append(ControlLayer(current, control, manifest, True))
                    break
                connection.row_factory = sqlite3.Row
                row = connection.execute("SELECT * FROM control_delta_metadata").fetchone()
                if row is None or row["schema_version"] != CONTROL_DELTA_SCHEMA or row["snapshot_id"] != current:
                    raise IncrementalControlError("invalid control delta metadata")
                parent = str(row["predecessor_snapshot_id"])
                parent_manifest = self._manifest_path(parent)
                if sha256_file(parent_manifest) != row["predecessor_manifest_sha256"]:
                    raise IncrementalControlError("control parent manifest binding mismatch")
                if control_member_hash(parent_manifest, self.control_relative_path) != row["predecessor_control_sha256"]:
                    raise IncrementalControlError("control parent content binding mismatch")
                layers.append(ControlLayer(current, control, manifest, False))
                current = parent
        return tuple(layers)

    @property
    def depth(self) -> int:
        return len(self.layers)

    def _tombstones(self, kind: str) -> set[str]:
        result: set[str] = set()
        for layer in self.layers:
            if layer.is_checkpoint:
                continue
            with closing(sqlite3.connect(f"file:{layer.control_path.as_posix()}?mode=ro", uri=True)) as connection:
                result.update(str(row[0]) for row in connection.execute(
                    "SELECT record_key FROM control_record_tombstone WHERE record_kind=?", (kind,)
                ))
        return result

    def _overrides(self, kind: str) -> dict[tuple[str, str], int]:
        result: dict[tuple[str, str], int] = {}
        for index, layer in enumerate(self.layers):
            if layer.is_checkpoint:
                continue
            with closing(sqlite3.connect(f"file:{layer.control_path.as_posix()}?mode=ro", uri=True)) as connection:
                for row in connection.execute(
                    "SELECT subject_type,subject_id FROM control_subject_override WHERE record_kind=?",
                    (kind,),
                ):
                    result.setdefault((str(row[0]), str(row[1])), index)
        return result

    def effective_rows(
        self,
        table: str,
        key_column: str,
        *,
        where_sql: str = "",
        params: Sequence[Any] = (),
        snapshot_scoped: bool = False,
        tombstone_kind: str | None = None,
        limit_per_layer: int | None = None,
    ) -> list[dict[str, Any]]:
        kind = tombstone_kind or table
        removed: set[str] = set()
        found: dict[str, dict[str, Any]] = {}
        for layer in self.layers:
            with closing(sqlite3.connect(f"file:{layer.control_path.as_posix()}?mode=ro", uri=True)) as connection:
                connection.row_factory = sqlite3.Row
                exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()
                if not exists:
                    continue
                predicate = where_sql
                values: list[Any] = list(params)
                if snapshot_scoped:
                    predicate = (predicate + " AND " if predicate else " WHERE ") + "snapshot_id=?"
                    values.append(layer.snapshot_id)
                limit_sql = " LIMIT ?" if limit_per_layer is not None else ""
                if limit_per_layer is not None:
                    values.append(limit_per_layer)
                for stored in connection.execute(f"SELECT * FROM {table}{predicate}{limit_sql}", values):
                    row = dict(stored); key = str(row[key_column])
                    if key not in removed and key not in found:
                        found[key] = row
                if not layer.is_checkpoint:
                    removed.update(str(row[0]) for row in connection.execute(
                        "SELECT record_key FROM control_record_tombstone WHERE record_kind=?",
                        (kind,),
                    ))
        return list(found.values())

    def subject(self, subject_type: str, subject_id: str) -> dict[str, Any] | None:
        rows = self.effective_rows(
            "subject_registry", "subject_id",
            where_sql=" WHERE subject_type=? AND subject_id=?",
            params=(subject_type, subject_id), tombstone_kind="subject",
        )
        return rows[0] if rows else None

    def subjects(self, subject_type: str | None = None) -> list[dict[str, Any]]:
        return self.effective_rows(
            "subject_registry", "subject_id",
            where_sql=" WHERE subject_type=?" if subject_type else "",
            params=(subject_type,) if subject_type else (), tombstone_kind="subject",
        )

    def aliases_matching(self, where_sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        return self.effective_rows(
            "subject_alias_registry", "alias_id", where_sql=where_sql,
            params=params, tombstone_kind="alias",
        )

    def relationships_matching(self, where_sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        return self.effective_rows(
            "subject_relationship_registry", "relationship_id", where_sql=where_sql,
            params=params, tombstone_kind="relationship",
        )

    def watermarks(self, metrics: Sequence[str]) -> dict[tuple[str, str, str], str]:
        result: dict[tuple[str, str, str], str] = {}
        placeholders = ",".join("?" for _ in metrics)
        for layer in self.layers:
            with closing(sqlite3.connect(f"file:{layer.control_path.as_posix()}?mode=ro", uri=True)) as connection:
                table = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='control_series_watermark'"
                ).fetchone()
                if table:
                    for subject_type, subject_id, metric_id, time_end in connection.execute(
                        f"SELECT subject_type,subject_id,metric_id,time_end FROM control_series_watermark WHERE metric_id IN ({placeholders})",
                        tuple(metrics),
                    ):
                        result.setdefault(
                            (str(subject_type), str(subject_id), str(metric_id)), str(time_end)
                        )
                    complete = connection.execute(
                        "SELECT complete_checkpoint FROM control_watermark_state WHERE singleton_id=1"
                    ).fetchone()
                    if complete and int(complete[0]) == 1:
                        self.last_resolution_stats = {
                            "control_layers_opened": self.layers.index(layer) + 1,
                            "watermark_rows_returned": len(result),
                            "historical_locator_rows_read": 0,
                        }
                        return result
        # Legacy complete checkpoints predate the compact watermark owner. This
        # one-time compatibility path is used until the first material delta
        # persists a complete compact watermark checkpoint.
        removed = self._tombstones("locator")
        for layer in self.layers:
            with closing(sqlite3.connect(f"file:{layer.control_path.as_posix()}?mode=ro", uri=True)) as connection:
                rows = connection.execute(
                    f"SELECT locator_id,subject_type,subject_id,metric_id,time_end,relative_path,content_sha256,layer_name FROM subject_partition_locator_registry WHERE snapshot_id=? AND layer_name='standard_facts' AND metric_id IN ({placeholders}) AND time_end IS NOT NULL",
                    (layer.snapshot_id, *metrics),
                )
                for locator_id, subject_type, subject_id, metric_id, time_end, path, digest, layer_name in rows:
                    if str(locator_id) in removed:
                        continue
                    if self.target_members.get(str(path)) != (str(layer_name), str(digest)):
                        continue
                    key = (str(subject_type), str(subject_id), str(metric_id))
                    result[key] = max(result.get(key, ""), str(time_end))
        self.last_resolution_stats = {
            "control_layers_opened": len(self.layers),
            "watermark_rows_returned": len(result),
            "legacy_checkpoint_locator_fallback": 1,
        }
        return result

    def has_complete_watermark_checkpoint(self) -> bool:
        for layer in self.layers:
            with closing(sqlite3.connect(f"file:{layer.control_path.as_posix()}?mode=ro", uri=True)) as connection:
                exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='control_watermark_state'"
                ).fetchone()
                if not exists:
                    continue
                row = connection.execute(
                    "SELECT complete_checkpoint FROM control_watermark_state WHERE singleton_id=1"
                ).fetchone()
                if row and int(row[0]) == 1:
                    return True
        return False

    def aliases(self, subject_type: str, subject_id: str) -> list[dict[str, Any]]:
        return self.effective_rows(
            "subject_alias_registry", "alias_id",
            where_sql=" WHERE subject_type=? AND subject_id=? AND acceptance_status='accepted'",
            params=(subject_type, subject_id), tombstone_kind="alias",
        )

    def relationships(self, subject_type: str, subject_id: str) -> list[dict[str, Any]]:
        return self.effective_rows(
            "subject_relationship_registry", "relationship_id",
            where_sql=" WHERE (from_type=? AND from_id=?) OR (to_type=? AND to_id=?)",
            params=(subject_type, subject_id, subject_type, subject_id),
            tombstone_kind="relationship",
        )

    def locators(
        self, *, layer_name: str, subject_type: str, subject_id: str,
        metric_id: str | None, time_start: str | None, time_end: str | None,
        scope_contains: Mapping[str, Any] | None = None, limit: int = 2048,
    ) -> list[dict[str, Any]]:
        if limit < 1 or limit > 2048:
            raise IncrementalControlError("locator result limit is outside the bounded contract")
        sql = " WHERE layer_name=? AND subject_type=? AND subject_id=? AND locator_status='accepted'"
        params: list[Any] = [layer_name, subject_type, subject_id]
        if metric_id is not None:
            sql += " AND (metric_id=? OR metric_id IS NULL)"; params.append(metric_id)
        if time_end is not None:
            sql += " AND (time_start IS NULL OR time_start<=?)"; params.append(time_end)
        if time_start is not None:
            sql += " AND (time_end IS NULL OR time_end>=?)"; params.append(time_start)
        rows = self.effective_rows(
            "subject_partition_locator_registry", "locator_id",
            where_sql=sql, params=params, snapshot_scoped=True, tombstone_kind="locator",
            limit_per_layer=limit,
        )
        required = dict(scope_contains or {})
        visible = []
        considered = len(rows)
        for row in rows:
            member = self.target_members.get(str(row["relative_path"]))
            if member != (str(row["layer_name"]), str(row["content_sha256"])):
                continue
            scope = json.loads(row["scope_json"])
            if any(scope.get(key) != value for key, value in required.items()):
                continue
            item = dict(row)
            item["origin_snapshot_id"] = item["snapshot_id"]
            item["snapshot_id"] = self.snapshot_id
            visible.append(item)
        visible.sort(key=lambda row: (row["relative_path"], row.get("row_group_start") or -1))
        self.last_resolution_stats = {
            "control_layers_opened": len(self.layers),
            "candidate_locator_rows_read": considered,
            "effective_locator_rows_returned": min(len(visible), limit),
            "business_payload_rows_read": 0,
        }
        return visible[:limit]

    def search(self, term: str, high: str, subject_types: Sequence[str], *, limit: int) -> list[dict[str, Any]]:
        removed: set[str] = set()
        overrides = self._overrides("fund_search")
        found: dict[str, dict[str, Any]] = {}
        placeholders = ",".join("?" for _ in subject_types)
        for index, layer in enumerate(self.layers):
            with closing(sqlite3.connect(f"file:{layer.control_path.as_posix()}?mode=ro", uri=True)) as connection:
                connection.row_factory = sqlite3.Row
                exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fund_search_index'").fetchone()
                if not exists:
                    continue
                rows = connection.execute(
                    f"SELECT * FROM fund_search_index WHERE snapshot_id=? AND normalized_term>=? AND normalized_term<? AND subject_type IN ({placeholders}) ORDER BY normalized_term,subject_type,subject_id LIMIT ?",
                    (layer.snapshot_id, term, high, *subject_types, limit * 8),
                )
                for stored in rows:
                    row = dict(stored); key = str(row["search_record_id"])
                    subject = (str(row["subject_type"]), str(row["subject_id"]))
                    if key in removed or key in found:
                        continue
                    if subject in overrides and overrides[subject] < index:
                        continue
                    found[key] = row
                if not layer.is_checkpoint:
                    removed.update(str(row[0]) for row in connection.execute(
                        "SELECT record_key FROM control_record_tombstone WHERE record_kind='fund_search'"
                    ))
        return list(found.values())[: limit * 8]

    def search_complete(
        self, term: str, high: str, subject_types: Sequence[str], *,
        raw_row_budget: int = 250_000,
    ) -> list[dict[str, Any]]:
        """Resolve every matching accepted alias across immutable control layers.

        Unlike the legacy bounded search, post-filtering and pagination may
        safely use this result. The budget bounds application memory; exceeding
        it is an explicit too-broad query, never a silently truncated result.
        The current five-layer Fund release has 141,247 total search rows and
        11,411 rows for a broad leading-digit probe, measured before adoption.
        """
        removed: set[str] = set()
        overrides = self._overrides("fund_search")
        found: dict[str, dict[str, Any]] = {}
        placeholders = ",".join("?" for _ in subject_types)
        predicate = f"snapshot_id=? AND normalized_term>=? AND normalized_term<? AND subject_type IN ({placeholders})"
        considered = 0
        for index, layer in enumerate(self.layers):
            with closing(sqlite3.connect(f"file:{layer.control_path.as_posix()}?mode=ro", uri=True)) as connection:
                connection.row_factory = sqlite3.Row
                exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fund_search_index'").fetchone()
                if not exists:
                    continue
                params = (layer.snapshot_id, term, high, *subject_types)
                count = int(connection.execute(f"SELECT COUNT(*) FROM fund_search_index WHERE {predicate}", params).fetchone()[0])
                considered += count
                if considered > raw_row_budget:
                    raise IncrementalControlSearchLimit("complete Fund discovery query exceeds the measured memory budget; narrow the search")
                for stored in connection.execute(
                    f"SELECT * FROM fund_search_index WHERE {predicate} ORDER BY normalized_term,subject_type,subject_id,search_record_id",
                    params,
                ):
                    row = dict(stored)
                    key = str(row["search_record_id"])
                    subject = (str(row["subject_type"]), str(row["subject_id"]))
                    if key in removed or key in found:
                        continue
                    if subject in overrides and overrides[subject] < index:
                        continue
                    found[key] = row
                if not layer.is_checkpoint:
                    removed.update(str(row[0]) for row in connection.execute(
                        "SELECT record_key FROM control_record_tombstone WHERE record_kind='fund_search'"
                    ))
        self.last_resolution_stats = {
            "control_layers_opened": len(self.layers),
            "matching_search_rows_considered": considered,
            "effective_search_rows_returned": len(found),
            "business_payload_rows_read": 0,
        }
        return list(found.values())

    def nonpromoted(self, subject_type: str, subject_id: str, metric_id: str, start: str | None, end: str | None) -> list[dict[str, Any]]:
        sql = " WHERE subject_type=? AND subject_id=? AND (metric_id IS NULL OR metric_id=?)"
        params: list[Any] = [subject_type, subject_id, metric_id]
        if end is not None:
            sql += " AND (time_start IS NULL OR time_start<=?)"; params.append(end)
        if start is not None:
            sql += " AND (time_end IS NULL OR time_end>=?)"; params.append(start)
        return self.effective_rows(
            "fund_nonpromoted_interval_index", "record_id", where_sql=sql,
            params=params, snapshot_scoped=True, tombstone_kind="fund_nonpromoted",
        )


def add_tombstones(
    connection: sqlite3.Connection,
    records: Iterable[Mapping[str, str]],
) -> int:
    ensure_delta_schema(connection)
    before = connection.total_changes
    connection.executemany(
        "INSERT OR REPLACE INTO control_record_tombstone VALUES (?,?,?,?)",
        [
            (str(row["record_kind"]), str(row["record_key"]), str(row["reason"]), str(row["created_at_utc"]))
            for row in records
        ],
    )
    return connection.total_changes - before


def add_subject_overrides(
    connection: sqlite3.Connection,
    record_kind: str,
    subjects: Iterable[tuple[str, str]],
    *,
    created_at_utc: str,
) -> int:
    ensure_delta_schema(connection)
    before = connection.total_changes
    connection.executemany(
        "INSERT OR REPLACE INTO control_subject_override VALUES (?,?,?,?)",
        [(record_kind, subject_type, subject_id, created_at_utc) for subject_type, subject_id in subjects],
    )
    return connection.total_changes - before
