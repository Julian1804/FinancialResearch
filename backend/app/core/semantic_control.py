from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = PROJECT_ROOT / "config" / "fr_authoritative_subject_registry_schema.json"
SEMANTIC_CONTROL_SCHEMA = "fr_shared_semantic_control_v1"
_RELATIONSHIP_TYPE = re.compile(r"^[a-z][a-z0-9_]*$")
_SCOPE_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class SemanticControlError(ValueError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_record_id(namespace: str, value: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(dict(value)).encode("utf-8")).hexdigest()
    return f"{namespace}:{digest}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@lru_cache(maxsize=1)
def semantic_contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def supported_subject_types() -> frozenset[str]:
    return frozenset(str(value) for value in semantic_contract()["required_subject_types"])


def allocatable_subject_types() -> frozenset[str]:
    compatibility_only = frozenset(
        str(value)
        for value in semantic_contract().get("compatibility_only_subject_types", ())
    )
    return supported_subject_types() - compatibility_only


def validate_subject_type(subject_type: str) -> None:
    if subject_type not in allocatable_subject_types():
        raise SemanticControlError(f"subject type is not available for active onboarding: {subject_type}")


def _validate_interval(effective_start: str | None, effective_end: str | None) -> None:
    if effective_start and effective_end and effective_end < effective_start:
        raise SemanticControlError("effective interval ends before it starts")


def _scope(scope: Mapping[str, Any]) -> tuple[str, str]:
    normalized = {str(key): value for key, value in dict(scope).items() if value is not None}
    if not normalized:
        raise SemanticControlError("a scoped record requires non-empty scope")
    if any(not _SCOPE_KEY.fullmatch(key) for key in normalized):
        raise SemanticControlError("scope keys must be stable field-name tokens")
    payload = canonical_json(normalized)
    return payload, hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _provenance(provenance_refs: Iterable[str]) -> str:
    values = sorted({str(value) for value in provenance_refs if str(value).strip()})
    if not values:
        raise SemanticControlError("accepted semantic records require provenance")
    return canonical_json(values)


def _subject_exists(connection: sqlite3.Connection, subject_type: str, subject_id: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM subject_registry WHERE subject_type=? AND subject_id=?",
        (subject_type, subject_id),
    ).fetchone()
    return row is not None


def _require_table_columns(
    connection: sqlite3.Connection,
    table: str,
    required: set[str],
) -> None:
    present = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    if present is None:
        raise SemanticControlError(f"snapshot manifest authority is missing table: {table}")
    actual = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
    if not required.issubset(actual):
        raise SemanticControlError(f"snapshot manifest authority has incompatible schema: {table}")


def _require_snapshot_manifest_owner(
    connection: sqlite3.Connection,
    snapshot_id: str,
) -> None:
    _require_table_columns(connection, "snapshot_catalog", {"snapshot_id"})
    _require_table_columns(
        connection,
        "partition_manifest",
        {"partition_id", "layer_name", "relative_path", "content_sha256", "completed"},
    )
    snapshots = [
        str(row[0]) for row in connection.execute("SELECT snapshot_id FROM snapshot_catalog")
    ]
    if snapshots != [snapshot_id]:
        raise SemanticControlError(
            "locator snapshot does not match the unique snapshot-local manifest owner"
        )


def verify_snapshot_manifest_member(
    connection: sqlite3.Connection,
    *,
    snapshot_id: str,
    layer_name: str,
    relative_path: str,
    content_sha256: str,
) -> dict[str, Any]:
    """Prove one locator target from the existing snapshot manifest owner."""
    _require_snapshot_manifest_owner(connection, snapshot_id)
    matches = connection.execute(
        """
        SELECT partition_id,layer_name,relative_path,content_sha256,completed
        FROM partition_manifest
        WHERE relative_path=?
        """,
        (relative_path,),
    ).fetchall()
    if len(matches) != 1:
        raise SemanticControlError("locator path is absent or ambiguous in the snapshot manifest")
    member = matches[0]
    if (
        str(member[1]) != layer_name
        or str(member[3]) != content_sha256
        or int(member[4]) != 1
    ):
        raise SemanticControlError(
            "locator layer or content hash does not match one completed manifest member"
        )
    return {
        "partition_id": str(member[0]),
        "layer_name": str(member[1]),
        "relative_path": str(member[2]),
        "content_sha256": str(member[3]),
    }


def ensure_semantic_control_schema(connection: sqlite3.Connection) -> None:
    """Install the shared snapshot-local semantic tables on an explicit owner.

    This function never opens a production database itself. A snapshot builder
    supplies the connection that belongs to its unpublished transaction.
    """
    required_columns = {
        "subject_registry": {"subject_type", "subject_id"},
        "subject_alias_registry": {
            "alias_id", "subject_type", "subject_id", "alias_type", "alias_value",
            "scope_json", "scope_sha256", "effective_start", "effective_end",
            "provenance_json", "acceptance_status", "updated_at_utc",
        },
        "subject_relationship_registry": {
            "relationship_id", "from_type", "from_id", "to_type", "to_id",
            "relationship_type", "effective_start", "effective_end",
            "attributes_json", "resolution_status", "updated_at_utc",
        },
        "subject_partition_locator_registry": {
            "locator_id", "snapshot_id", "layer_name", "subject_type", "subject_id",
            "metric_id", "scope_json", "time_start", "time_end", "relative_path",
            "content_sha256", "row_group_start", "row_group_end", "locator_status",
            "updated_at_utc",
        },
    }
    present = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for table, required in required_columns.items():
        if table in present:
            actual = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
            if not required.issubset(actual):
                raise SemanticControlError(f"semantic control table has incompatible schema: {table}")
    if set(required_columns).issubset(present):
        return

    # Execute DDL one statement at a time. sqlite3.Connection.executescript()
    # commits a pending transaction implicitly, which would break the caller's
    # unpublished-snapshot transaction and rollback boundary.
    statements = (
        """CREATE TABLE IF NOT EXISTS subject_registry(
          subject_type TEXT NOT NULL, subject_id TEXT NOT NULL, domain TEXT NOT NULL,
          legacy_alias TEXT, market TEXT, venue TEXT, effective_start TEXT, effective_end TEXT,
          code_aliases_json TEXT NOT NULL, attributes_json TEXT NOT NULL,
          resolution_status TEXT NOT NULL, updated_at_utc TEXT NOT NULL,
          PRIMARY KEY(subject_type,subject_id)
        )""",
        """CREATE TABLE IF NOT EXISTS subject_alias_registry(
          alias_id TEXT PRIMARY KEY,
          subject_type TEXT NOT NULL,
          subject_id TEXT NOT NULL,
          alias_type TEXT NOT NULL,
          alias_value TEXT NOT NULL,
          scope_json TEXT NOT NULL,
          scope_sha256 TEXT NOT NULL,
          effective_start TEXT,
          effective_end TEXT,
          provenance_json TEXT NOT NULL,
          acceptance_status TEXT NOT NULL,
          updated_at_utc TEXT NOT NULL
        )""",
        """CREATE INDEX IF NOT EXISTS idx_subject_alias_lookup
          ON subject_alias_registry(
            alias_type,alias_value,scope_sha256,effective_start,effective_end
          )""",
        """CREATE INDEX IF NOT EXISTS idx_subject_alias_subject
          ON subject_alias_registry(subject_type,subject_id)""",
        """CREATE TABLE IF NOT EXISTS subject_relationship_registry(
          relationship_id TEXT PRIMARY KEY, from_type TEXT NOT NULL, from_id TEXT NOT NULL,
          to_type TEXT NOT NULL, to_id TEXT NOT NULL, relationship_type TEXT NOT NULL,
          effective_start TEXT, effective_end TEXT, attributes_json TEXT NOT NULL,
          resolution_status TEXT NOT NULL, updated_at_utc TEXT NOT NULL
        )""",
        """CREATE INDEX IF NOT EXISTS idx_subject_relationship_from
          ON subject_relationship_registry(from_type,from_id,relationship_type)""",
        """CREATE INDEX IF NOT EXISTS idx_subject_relationship_to
          ON subject_relationship_registry(to_type,to_id,relationship_type)""",
        """CREATE TABLE IF NOT EXISTS subject_partition_locator_registry(
          locator_id TEXT PRIMARY KEY,
          snapshot_id TEXT NOT NULL,
          layer_name TEXT NOT NULL,
          subject_type TEXT NOT NULL,
          subject_id TEXT NOT NULL,
          metric_id TEXT,
          scope_json TEXT NOT NULL,
          time_start TEXT,
          time_end TEXT,
          relative_path TEXT NOT NULL,
          content_sha256 TEXT NOT NULL,
          row_group_start INTEGER,
          row_group_end INTEGER,
          locator_status TEXT NOT NULL,
          updated_at_utc TEXT NOT NULL
        )""",
        """CREATE INDEX IF NOT EXISTS idx_subject_partition_locator_lookup
          ON subject_partition_locator_registry(
            snapshot_id,subject_type,subject_id,layer_name,metric_id,time_start,time_end
          )""",
    )
    for statement in statements:
        connection.execute(statement)
    ensure_semantic_control_schema(connection)


def canonical_alias_record(
    *,
    subject_type: str,
    subject_id: str,
    alias_type: str,
    alias_value: str,
    scope: Mapping[str, Any],
    effective_start: str | None,
    effective_end: str | None,
    provenance_refs: Iterable[str],
    updated_at_utc: str | None = None,
) -> dict[str, Any]:
    validate_subject_type(subject_type)
    if not alias_type or not alias_value:
        raise SemanticControlError("alias type and value are required")
    _validate_interval(effective_start, effective_end)
    scope_json, scope_sha256 = _scope(scope)
    provenance_json = _provenance(provenance_refs)
    identity = {
        "alias_type": alias_type,
        "alias_value": alias_value,
        "effective_end": effective_end,
        "effective_start": effective_start,
        "scope_sha256": scope_sha256,
        "subject_id": subject_id,
        "subject_type": subject_type,
    }
    return {
        "alias_id": stable_record_id("subject_alias", identity),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "alias_type": alias_type,
        "alias_value": alias_value,
        "scope_json": scope_json,
        "scope_sha256": scope_sha256,
        "effective_start": effective_start,
        "effective_end": effective_end,
        "provenance_json": provenance_json,
        "acceptance_status": "accepted",
        "updated_at_utc": updated_at_utc or utc_now(),
    }


def _intervals_overlap(
    start_a: str | None,
    end_a: str | None,
    start_b: str | None,
    end_b: str | None,
) -> bool:
    return (end_a is None or start_b is None or start_b <= end_a) and (
        end_b is None or start_a is None or start_a <= end_b
    )


def register_alias(connection: sqlite3.Connection, record: Mapping[str, Any]) -> None:
    ensure_semantic_control_schema(connection)
    row = dict(record)
    try:
        expected = canonical_alias_record(
            subject_type=str(row["subject_type"]),
            subject_id=str(row["subject_id"]),
            alias_type=str(row["alias_type"]),
            alias_value=str(row["alias_value"]),
            scope=json.loads(row["scope_json"]),
            effective_start=row.get("effective_start"),
            effective_end=row.get("effective_end"),
            provenance_refs=json.loads(row["provenance_json"]),
            updated_at_utc=str(row["updated_at_utc"]),
        )
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SemanticControlError("alias record is malformed") from exc
    if row != expected:
        raise SemanticControlError("alias record is not canonical")
    if not _subject_exists(connection, str(row["subject_type"]), str(row["subject_id"])):
        raise SemanticControlError("alias subject is absent from the snapshot subject registry")
    conflicts = connection.execute(
        """
        SELECT subject_type,subject_id,effective_start,effective_end
        FROM subject_alias_registry
        WHERE alias_type=? AND alias_value=? AND scope_sha256=?
          AND alias_id<>?
        """,
        (row["alias_type"], row["alias_value"], row["scope_sha256"], row["alias_id"]),
    ).fetchall()
    for subject_type, subject_id, start, end in conflicts:
        if (subject_type, subject_id) != (row["subject_type"], row["subject_id"]) and _intervals_overlap(
            start, end, row.get("effective_start"), row.get("effective_end")
        ):
            raise SemanticControlError("one scoped alias overlaps different accepted subjects")
    columns = tuple(row)
    placeholders = ",".join("?" for _ in columns)
    connection.execute(
        f"INSERT OR IGNORE INTO subject_alias_registry({','.join(columns)}) VALUES({placeholders})",
        tuple(row[column] for column in columns),
    )


def resolve_alias(
    connection: sqlite3.Connection,
    *,
    alias_type: str,
    alias_value: str,
    scope: Mapping[str, Any],
    effective_at: str,
) -> dict[str, str]:
    ensure_semantic_control_schema(connection)
    _, scope_sha256 = _scope(scope)
    rows = connection.execute(
        """
        SELECT subject_type,subject_id FROM subject_alias_registry
        WHERE alias_type=? AND alias_value=? AND scope_sha256=?
          AND acceptance_status='accepted'
          AND (effective_start IS NULL OR effective_start<=?)
          AND (effective_end IS NULL OR effective_end>=?)
        """,
        (alias_type, alias_value, scope_sha256, effective_at, effective_at),
    ).fetchall()
    subjects = sorted({(str(row[0]), str(row[1])) for row in rows})
    if not subjects:
        raise KeyError("no accepted alias binding at the requested effective time")
    if len(subjects) != 1:
        raise SemanticControlError("accepted alias binding is ambiguous")
    return {"subject_type": subjects[0][0], "subject_id": subjects[0][1]}


def canonical_relationship_record(
    *,
    from_type: str,
    from_id: str,
    to_type: str,
    to_id: str,
    relationship_type: str,
    definition_ref: str,
    effective_start: str | None,
    effective_end: str | None,
    provenance_refs: Iterable[str],
    attributes: Mapping[str, Any] | None = None,
    updated_at_utc: str | None = None,
) -> dict[str, Any]:
    validate_subject_type(from_type)
    validate_subject_type(to_type)
    if not _RELATIONSHIP_TYPE.fullmatch(relationship_type):
        raise SemanticControlError("relationship type must be a stable snake-case token")
    if not definition_ref:
        raise SemanticControlError("relationship definition reference is required")
    _validate_interval(effective_start, effective_end)
    identity = {
        "effective_end": effective_end,
        "effective_start": effective_start,
        "from_id": from_id,
        "from_type": from_type,
        "relationship_type": relationship_type,
        "to_id": to_id,
        "to_type": to_type,
    }
    details = dict(attributes or {})
    details.update(
        {
            "definition_ref": definition_ref,
            "provenance_refs": json.loads(_provenance(provenance_refs)),
            "semantic_control_schema": SEMANTIC_CONTROL_SCHEMA,
        }
    )
    return {
        "relationship_id": stable_record_id("subject_relationship", identity),
        "from_type": from_type,
        "from_id": from_id,
        "to_type": to_type,
        "to_id": to_id,
        "relationship_type": relationship_type,
        "effective_start": effective_start,
        "effective_end": effective_end,
        "attributes_json": canonical_json(details),
        "resolution_status": "accepted",
        "updated_at_utc": updated_at_utc or utc_now(),
    }


def register_relationship(connection: sqlite3.Connection, record: Mapping[str, Any]) -> None:
    ensure_semantic_control_schema(connection)
    row = dict(record)
    try:
        details = json.loads(row["attributes_json"])
        definition_ref = details.pop("definition_ref")
        provenance_refs = details.pop("provenance_refs")
        semantic_schema = details.pop("semantic_control_schema")
        expected = canonical_relationship_record(
            from_type=str(row["from_type"]),
            from_id=str(row["from_id"]),
            to_type=str(row["to_type"]),
            to_id=str(row["to_id"]),
            relationship_type=str(row["relationship_type"]),
            definition_ref=str(definition_ref),
            effective_start=row.get("effective_start"),
            effective_end=row.get("effective_end"),
            provenance_refs=provenance_refs,
            attributes=details,
            updated_at_utc=str(row["updated_at_utc"]),
        )
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SemanticControlError("relationship record is malformed") from exc
    if semantic_schema != SEMANTIC_CONTROL_SCHEMA or row != expected:
        raise SemanticControlError("relationship record is not canonical")
    for subject_type, subject_id in (
        (str(row["from_type"]), str(row["from_id"])),
        (str(row["to_type"]), str(row["to_id"])),
    ):
        validate_subject_type(subject_type)
        if not _subject_exists(connection, subject_type, subject_id):
            raise SemanticControlError("relationship endpoint is absent from subject registry")
    columns = tuple(row)
    placeholders = ",".join("?" for _ in columns)
    connection.execute(
        f"INSERT OR IGNORE INTO subject_relationship_registry({','.join(columns)}) VALUES({placeholders})",
        tuple(row[column] for column in columns),
    )


def canonical_locator_record(
    *,
    snapshot_id: str,
    layer_name: str,
    subject_type: str,
    subject_id: str,
    metric_id: str | None,
    scope: Mapping[str, Any],
    time_start: str | None,
    time_end: str | None,
    relative_path: str,
    content_sha256: str,
    row_group_start: int | None = None,
    row_group_end: int | None = None,
    updated_at_utc: str | None = None,
) -> dict[str, Any]:
    validate_subject_type(subject_type)
    allowed_layers = set(semantic_contract()["snapshot_locator_contract"]["allowed_layers"])
    if layer_name not in allowed_layers:
        raise SemanticControlError(f"unsupported locator layer: {layer_name}")
    _validate_interval(time_start, time_end)
    path = PurePosixPath(relative_path)
    if path.is_absolute() or ".." in path.parts or str(path) != relative_path:
        raise SemanticControlError("locator path must be normalized and snapshot-relative")
    if not _HEX64.fullmatch(content_sha256):
        raise SemanticControlError("locator content hash must be lowercase SHA-256")
    if (row_group_start is None) != (row_group_end is None):
        raise SemanticControlError("locator row-group bounds must both be present or absent")
    if row_group_start is not None and (row_group_start < 0 or row_group_end < row_group_start):
        raise SemanticControlError("invalid locator row-group interval")
    normalized_scope = {
        str(key): value for key, value in dict(scope).items() if value is not None
    }
    if any(not _SCOPE_KEY.fullmatch(key) for key in normalized_scope):
        raise SemanticControlError("scope keys must be stable field-name tokens")
    scope_json = canonical_json(normalized_scope)
    identity = {
        "content_sha256": content_sha256,
        "layer_name": layer_name,
        "metric_id": metric_id,
        "relative_path": relative_path,
        "row_group_end": row_group_end,
        "row_group_start": row_group_start,
        "scope_json": scope_json,
        "snapshot_id": snapshot_id,
        "subject_id": subject_id,
        "subject_type": subject_type,
        "time_end": time_end,
        "time_start": time_start,
    }
    return {
        "locator_id": stable_record_id("subject_partition_locator", identity),
        "snapshot_id": snapshot_id,
        "layer_name": layer_name,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "metric_id": metric_id,
        "scope_json": scope_json,
        "time_start": time_start,
        "time_end": time_end,
        "relative_path": relative_path,
        "content_sha256": content_sha256,
        "row_group_start": row_group_start,
        "row_group_end": row_group_end,
        "locator_status": "accepted",
        "updated_at_utc": updated_at_utc or utc_now(),
    }


def register_locator(connection: sqlite3.Connection, record: Mapping[str, Any]) -> None:
    row = dict(record)
    try:
        expected = canonical_locator_record(
            snapshot_id=str(row["snapshot_id"]),
            layer_name=str(row["layer_name"]),
            subject_type=str(row["subject_type"]),
            subject_id=str(row["subject_id"]),
            metric_id=row.get("metric_id"),
            scope=json.loads(row["scope_json"]),
            time_start=row.get("time_start"),
            time_end=row.get("time_end"),
            relative_path=str(row["relative_path"]),
            content_sha256=str(row["content_sha256"]),
            row_group_start=row.get("row_group_start"),
            row_group_end=row.get("row_group_end"),
            updated_at_utc=str(row["updated_at_utc"]),
        )
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SemanticControlError("locator record is malformed") from exc
    if row != expected:
        raise SemanticControlError("locator record is not canonical")
    verify_snapshot_manifest_member(
        connection,
        snapshot_id=str(row["snapshot_id"]),
        layer_name=str(row["layer_name"]),
        relative_path=str(row["relative_path"]),
        content_sha256=str(row["content_sha256"]),
    )
    ensure_semantic_control_schema(connection)
    if not _subject_exists(connection, str(row["subject_type"]), str(row["subject_id"])):
        raise SemanticControlError("locator subject is absent from subject registry")
    columns = tuple(row)
    placeholders = ",".join("?" for _ in columns)
    connection.execute(
        f"INSERT OR IGNORE INTO subject_partition_locator_registry({','.join(columns)}) VALUES({placeholders})",
        tuple(row[column] for column in columns),
    )


def register_locators_batch(
    connection: sqlite3.Connection,
    records: Iterable[Mapping[str, Any]],
    *,
    subject_exists: Any | None = None,
) -> int:
    """Register many manifest-proved locators without repeating path checks.

    Large canonical populations can legitimately have hundreds of thousands of
    subject/year row-group locators.  The scalar contract remains authoritative,
    but repeatedly querying the same manifest member for every row is needless
    control-plane I/O.  This batch route canonicalizes every record, proves each
    distinct member once, verifies every subject endpoint, and inserts the whole
    set in the caller's transaction.
    """
    ensure_semantic_control_schema(connection)
    materialized = [dict(record) for record in records]
    if not materialized:
        return 0
    canonical_rows: list[dict[str, Any]] = []
    member_keys: set[tuple[str, str, str, str]] = set()
    subject_keys: set[tuple[str, str]] = set()
    for row in materialized:
        try:
            expected = canonical_locator_record(
                snapshot_id=str(row["snapshot_id"]),
                layer_name=str(row["layer_name"]),
                subject_type=str(row["subject_type"]),
                subject_id=str(row["subject_id"]),
                metric_id=row.get("metric_id"),
                scope=json.loads(row["scope_json"]),
                time_start=row.get("time_start"),
                time_end=row.get("time_end"),
                relative_path=str(row["relative_path"]),
                content_sha256=str(row["content_sha256"]),
                row_group_start=row.get("row_group_start"),
                row_group_end=row.get("row_group_end"),
                updated_at_utc=str(row["updated_at_utc"]),
            )
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise SemanticControlError("locator record is malformed") from exc
        if row != expected:
            raise SemanticControlError("locator record is not canonical")
        canonical_rows.append(row)
        member_keys.add(
            (
                str(row["snapshot_id"]), str(row["layer_name"]),
                str(row["relative_path"]), str(row["content_sha256"]),
            )
        )
        subject_keys.add((str(row["subject_type"]), str(row["subject_id"])))
    if len({row["snapshot_id"] for row in canonical_rows}) != 1:
        raise SemanticControlError("one locator batch cannot mix snapshots")
    for snapshot_id, layer_name, relative_path, content_sha256 in sorted(member_keys):
        verify_snapshot_manifest_member(
            connection,
            snapshot_id=snapshot_id,
            layer_name=layer_name,
            relative_path=relative_path,
            content_sha256=content_sha256,
        )
    exists = subject_exists or (lambda subject_type, subject_id: _subject_exists(
        connection, subject_type, subject_id
    ))
    missing = [
        (subject_type, subject_id)
        for subject_type, subject_id in sorted(subject_keys)
        if not exists(subject_type, subject_id)
    ]
    if missing:
        raise SemanticControlError(f"locator subjects are absent from subject registry: {missing[:3]}")
    columns = tuple(canonical_rows[0])
    if any(tuple(row) != columns for row in canonical_rows):
        raise SemanticControlError("locator batch columns are inconsistent")
    placeholders = ",".join("?" for _ in columns)
    before = connection.total_changes
    connection.executemany(
        f"INSERT OR IGNORE INTO subject_partition_locator_registry({','.join(columns)}) VALUES({placeholders})",
        [tuple(row[column] for column in columns) for row in canonical_rows],
    )
    return connection.total_changes - before


def resolve_subject_locators(
    connection: sqlite3.Connection,
    *,
    snapshot_id: str,
    layer_name: str,
    subject_type: str,
    subject_id: str,
    metric_id: str | None,
    time_start: str | None,
    time_end: str | None,
    scope_contains: Mapping[str, Any] | None = None,
    limit: int = 2048,
) -> list[dict[str, Any]]:
    _require_snapshot_manifest_owner(connection, snapshot_id)
    ensure_semantic_control_schema(connection)
    if limit < 1 or limit > 2048:
        raise SemanticControlError("locator result limit is outside the bounded contract")
    _validate_interval(time_start, time_end)
    required_scope = {
        str(key): value
        for key, value in dict(scope_contains or {}).items()
        if value is not None
    }
    if any(not _SCOPE_KEY.fullmatch(key) for key in required_scope):
        raise SemanticControlError("scope keys must be stable field-name tokens")
    scope_predicate = "".join(
        " AND json_extract(scope_json, ?) = json_extract(?, '$')"
        for _ in required_scope
    )
    params: list[Any] = [
        snapshot_id, layer_name, subject_type, subject_id,
        metric_id, metric_id, time_end, time_end, time_start, time_start,
    ]
    for key, value in required_scope.items():
        params.extend([f"$.{key}", canonical_json(value)])
    params.append(limit)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT * FROM subject_partition_locator_registry
        WHERE snapshot_id=? AND layer_name=? AND subject_type=? AND subject_id=?
          AND locator_status='accepted'
          AND (? IS NULL OR metric_id=? OR metric_id IS NULL)
          AND (? IS NULL OR time_start IS NULL OR time_start<=?)
          AND (? IS NULL OR time_end IS NULL OR time_end>=?)
        """ + scope_predicate + """
        ORDER BY relative_path,row_group_start
        LIMIT ?
        """,
        params,
    ).fetchall()
    result = [dict(row) for row in rows]
    for row in result:
        verify_snapshot_manifest_member(
            connection,
            snapshot_id=snapshot_id,
            layer_name=str(row["layer_name"]),
            relative_path=str(row["relative_path"]),
            content_sha256=str(row["content_sha256"]),
        )
    return result


def inherit_snapshot_locators(
    predecessor_connection: sqlite3.Connection,
    successor_connection: sqlite3.Connection,
    *,
    predecessor_snapshot_id: str,
    successor_snapshot_id: str,
    inherited_manifest_hashes: Mapping[str, str],
    replacement_records: Iterable[Mapping[str, Any]],
) -> dict[str, int]:
    """Carry only manifest-proved unchanged locators into a successor owner."""
    _require_snapshot_manifest_owner(predecessor_connection, predecessor_snapshot_id)
    _require_snapshot_manifest_owner(successor_connection, successor_snapshot_id)
    ensure_semantic_control_schema(predecessor_connection)
    ensure_semantic_control_schema(successor_connection)
    predecessor_connection.row_factory = sqlite3.Row
    predecessor = predecessor_connection.execute(
        "SELECT * FROM subject_partition_locator_registry WHERE snapshot_id=?",
        (predecessor_snapshot_id,),
    ).fetchall()
    replacements = [dict(row) for row in replacement_records]
    replacement_paths = {str(row["relative_path"]) for row in replacements}
    inherited_paths = {str(path): str(digest) for path, digest in inherited_manifest_hashes.items()}
    overlap = replacement_paths & set(inherited_paths)
    if overlap:
        raise SemanticControlError("a successor path cannot be both inherited and replaced")
    for path, digest in inherited_paths.items():
        successor_rows = successor_connection.execute(
            "SELECT layer_name FROM partition_manifest WHERE relative_path=?",
            (path,),
        ).fetchall()
        if len(successor_rows) != 1:
            raise SemanticControlError("planned inherited path is absent or ambiguous in successor manifest")
        verify_snapshot_manifest_member(
            successor_connection,
            snapshot_id=successor_snapshot_id,
            layer_name=str(successor_rows[0][0]),
            relative_path=path,
            content_sha256=digest,
        )
    inherited = 0
    for stored in predecessor:
        row = dict(stored)
        path = str(row["relative_path"])
        if path in replacement_paths:
            continue
        if path not in inherited_paths:
            continue
        verify_snapshot_manifest_member(
            predecessor_connection,
            snapshot_id=predecessor_snapshot_id,
            layer_name=str(row["layer_name"]),
            relative_path=path,
            content_sha256=str(row["content_sha256"]),
        )
        if inherited_paths[path] != row["content_sha256"]:
            raise SemanticControlError("planned inherited hash differs from predecessor locator")
        clone = canonical_locator_record(
            snapshot_id=successor_snapshot_id,
            layer_name=row["layer_name"],
            subject_type=row["subject_type"],
            subject_id=row["subject_id"],
            metric_id=row["metric_id"],
            scope=json.loads(row["scope_json"]),
            time_start=row["time_start"],
            time_end=row["time_end"],
            relative_path=path,
            content_sha256=row["content_sha256"],
            row_group_start=row["row_group_start"],
            row_group_end=row["row_group_end"],
        )
        register_locator(successor_connection, clone)
        inherited += 1
    for row in replacements:
        if row["snapshot_id"] != successor_snapshot_id:
            raise SemanticControlError("replacement locator targets another snapshot")
        register_locator(successor_connection, row)
    return {"inherited_locator_count": inherited, "replacement_locator_count": len(replacements)}
