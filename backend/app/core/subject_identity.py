"""Shared canonical subject onboarding at the ``standard_id_ready`` boundary.

The allocator intentionally does not derive FR subject IDs from discovery
evidence.  Names, exchange codes, provider records, ISINs, lifecycle evidence
IDs, and dates belong in external-identifier or provenance records.  A new FR
ID is an internally assigned immutable token persisted with the accepted
identity decision.  Re-reading or amending that decision reuses the token.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from backend.app.core.semantic_control import (
    allocatable_subject_types,
    supported_subject_types,
)

COMPATIBLE_SUBJECT_TYPES = supported_subject_types()
SUBJECT_TYPES = allocatable_subject_types()
READY_STATE = "standard_id_ready"
IDENTITY_STATE_SCHEMA = "fr_installation_identity_state_v1"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _atomic_write_ndjson(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(_canonical_json(dict(row)) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _new_internal_id(namespace: str) -> str:
    """Assign an opaque internal token; no business or evidence input is used."""
    return f"{namespace}:{uuid.uuid4().hex}"


class IdentityDecisionLedger:
    """Persistent owner for accepted identity decisions and assigned FR IDs.

    Callers retain the returned ``identity_decision_id`` and use it for every
    amendment.  Discovery evidence may change, but it can only amend provenance;
    it cannot regenerate or replace ``subject_id``.
    """

    def __init__(self, path: Path):
        self.path = path
        self._rows: dict[str, dict[str, Any]] = {}
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                decision_id = row["identity_decision_id"]
                if decision_id in self._rows:
                    raise ValueError(f"duplicate identity decision: {decision_id}")
                self._rows[decision_id] = row
        self._validate()

    def _validate(self) -> None:
        subject_ids: set[str] = set()
        for row in self._rows.values():
            if row["subject_type"] not in COMPATIBLE_SUBJECT_TYPES:
                raise ValueError(f"unsupported subject type: {row['subject_type']}")
            if row["decision_state"] != READY_STATE:
                raise ValueError(f"identity decision is not standard_id_ready: {row['identity_decision_id']}")
            if row["subject_id"] in subject_ids:
                raise ValueError(f"duplicate assigned subject ID: {row['subject_id']}")
            subject_ids.add(row["subject_id"])

    def rows(self) -> list[dict[str, Any]]:
        return [dict(self._rows[key]) for key in sorted(self._rows)]

    def get(self, identity_decision_id: str) -> dict[str, Any]:
        return dict(self._rows[identity_decision_id])

    def create(
        self,
        *,
        subject_type: str,
        accepted_identity_statement: str,
        economic_object_type: str,
        existing_subject_id: str | None = None,
        provenance_refs: Iterable[str] = (),
        decision_attributes: Mapping[str, Any] | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        if subject_type not in SUBJECT_TYPES:
            raise ValueError(f"unsupported subject type: {subject_type}")
        decision_id = _new_internal_id("identity_decision")
        subject_id = existing_subject_id or _new_internal_id(subject_type)
        row = {
            "identity_decision_id": decision_id,
            "decision_state": READY_STATE,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "allocation_action": "reuse_existing" if existing_subject_id else "assign_new_internal_id",
            "accepted_identity_statement": accepted_identity_statement,
            "economic_object_type": economic_object_type,
            "decision_attributes": dict(decision_attributes or {}),
            "provenance_refs": sorted(set(provenance_refs)),
            "identity_inputs_excluded_from_subject_id": [
                "name", "exchange_code", "provider_record_id", "lifecycle_evidence_id",
                "isin", "effective_date", "source_document",
            ],
        }
        self._rows[decision_id] = row
        self._validate()
        if persist:
            self.save()
        return dict(row)

    def amend_provenance(
        self,
        identity_decision_id: str,
        *,
        provenance_refs: Iterable[str],
        decision_attributes: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = self._rows[identity_decision_id]
        original_subject_id = row["subject_id"]
        row["provenance_refs"] = sorted(set(row.get("provenance_refs", ())) | set(provenance_refs))
        if decision_attributes:
            row["decision_attributes"] = {**row.get("decision_attributes", {}), **dict(decision_attributes)}
        if row["subject_id"] != original_subject_id:
            raise AssertionError("provenance amendment changed immutable subject ID")
        self.save()
        return dict(row)

    def save(self) -> None:
        self._validate()
        _atomic_write_ndjson(self.path, self.rows())


def validate_external_identifier(row: Mapping[str, Any]) -> None:
    """Require external identifiers to reference, never define, an FR subject."""
    required = {"external_identifier_id", "subject_id", "identifier_type", "identifier_value", "scope"}
    missing = sorted(required - set(row))
    if missing:
        raise ValueError(f"external identifier missing fields: {missing}")
    if row["subject_id"] == row["identifier_value"]:
        raise ValueError("external identifier must not be promoted as the FR subject ID")


class InstallationIdentityState:
    """Small installation-local authority for durable FR subject assignments.

    The state is deliberately separate from fact/history storage and from a
    generated control database.  Normal rebuilds open this owner first.  Only
    ``reset_database_generation`` can abandon its UUID space, and that method
    requires the caller to name the generation being abandoned explicitly.
    """

    def __init__(self, path: Path, backup_root: Path, *, create: bool = False):
        self.path = path
        self.backup_root = backup_root
        if create and not path.exists():
            self._initialize_new_file(installation_id=None)
        if not path.is_file():
            raise FileNotFoundError(f"installation identity state does not exist: {path}")
        self._validate_schema()

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Open one explicitly owned connection and always close it."""
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    def _initialize_new_file(self, installation_id: str | None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            raise FileExistsError(self.path)
        conn = sqlite3.connect(self.path)
        try:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=FULL;
                CREATE TABLE identity_state_metadata (
                    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
                    schema_version TEXT NOT NULL,
                    installation_id TEXT NOT NULL,
                    database_generation_id TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL
                );
                CREATE TABLE identity_decision_assignment (
                    identity_decision_id TEXT PRIMARY KEY,
                    database_generation_id TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL UNIQUE,
                    allocation_action TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    accepted_at_utc TEXT NOT NULL
                );
                CREATE TABLE accepted_identity_crosswalk (
                    crosswalk_id TEXT PRIMARY KEY,
                    database_generation_id TEXT NOT NULL,
                    identity_decision_id TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    authority TEXT NOT NULL,
                    identifier_type TEXT NOT NULL,
                    identifier_value TEXT NOT NULL,
                    scope_json TEXT NOT NULL,
                    scope_sha256 TEXT NOT NULL,
                    effective_start TEXT,
                    effective_end TEXT,
                    provenance_json TEXT NOT NULL,
                    accepted_at_utc TEXT NOT NULL,
                    FOREIGN KEY(identity_decision_id)
                        REFERENCES identity_decision_assignment(identity_decision_id)
                );
                CREATE INDEX idx_identity_crosswalk_lookup
                    ON accepted_identity_crosswalk(
                        authority,identifier_type,identifier_value,scope_sha256,
                        effective_start,effective_end
                    );
            """)
            conn.execute(
                "INSERT INTO identity_state_metadata VALUES (1,?,?,?,?)",
                (
                    IDENTITY_STATE_SCHEMA,
                    installation_id or _new_internal_id("installation"),
                    _new_internal_id("database_generation"),
                    self._utc_now(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def metadata(self) -> dict[str, Any]:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM identity_state_metadata WHERE singleton_id=1").fetchone()
        if row is None:
            raise ValueError("identity state metadata is missing")
        return dict(row)

    def _validate_schema(self) -> None:
        with self._connection() as conn:
            conn.execute("BEGIN")
            metadata_row = conn.execute(
                "SELECT * FROM identity_state_metadata WHERE singleton_id=1"
            ).fetchone()
            if metadata_row is None:
                raise ValueError("identity state metadata is missing")
            metadata = dict(metadata_row)
            if metadata["schema_version"] != IDENTITY_STATE_SCHEMA:
                raise ValueError(f"unsupported identity state schema: {metadata['schema_version']}")
            mixed = conn.execute(
                "SELECT COUNT(*) FROM identity_decision_assignment WHERE database_generation_id<>?",
                (metadata["database_generation_id"],),
            ).fetchone()[0]
            crosswalk_table = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                "AND name='accepted_identity_crosswalk'"
            ).fetchone()[0]
            crosswalk_mixed = 0
            crosswalk_detached = 0
            if crosswalk_table:
                crosswalk_mixed = conn.execute(
                    "SELECT COUNT(*) FROM accepted_identity_crosswalk "
                    "WHERE database_generation_id<>?",
                    (metadata["database_generation_id"],),
                ).fetchone()[0]
                crosswalk_detached = conn.execute(
                    """
                    SELECT COUNT(*) FROM accepted_identity_crosswalk c
                    LEFT JOIN identity_decision_assignment d
                      ON d.identity_decision_id=c.identity_decision_id
                    WHERE d.identity_decision_id IS NULL
                       OR c.subject_type<>d.subject_type
                       OR c.subject_id<>d.subject_id
                    """
                ).fetchone()[0]
        if mixed:
            raise ValueError("identity state mixes database generations")
        if crosswalk_mixed:
            raise ValueError("accepted identity crosswalk mixes database generations")
        if crosswalk_detached:
            raise ValueError("accepted identity crosswalk is detached from its identity decision")

    def install_identity_crosswalk_contract(self) -> None:
        """Install the optional reuse index without changing any assignment."""
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS accepted_identity_crosswalk (
                    crosswalk_id TEXT PRIMARY KEY,
                    database_generation_id TEXT NOT NULL,
                    identity_decision_id TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    authority TEXT NOT NULL,
                    identifier_type TEXT NOT NULL,
                    identifier_value TEXT NOT NULL,
                    scope_json TEXT NOT NULL,
                    scope_sha256 TEXT NOT NULL,
                    effective_start TEXT,
                    effective_end TEXT,
                    provenance_json TEXT NOT NULL,
                    accepted_at_utc TEXT NOT NULL,
                    FOREIGN KEY(identity_decision_id)
                        REFERENCES identity_decision_assignment(identity_decision_id)
                );
                CREATE INDEX IF NOT EXISTS idx_identity_crosswalk_lookup
                    ON accepted_identity_crosswalk(
                        authority,identifier_type,identifier_value,scope_sha256,
                        effective_start,effective_end
                    );
                """
            )

    @staticmethod
    def _intervals_overlap(
        start_a: str | None,
        end_a: str | None,
        start_b: str | None,
        end_b: str | None,
    ) -> bool:
        return (end_a is None or start_b is None or start_b <= end_a) and (
            end_b is None or start_a is None or start_a <= end_b
        )

    def register_accepted_crosswalk(
        self,
        *,
        identity_decision_id: str,
        subject_type: str,
        subject_id: str,
        authority: str,
        identifier_type: str,
        identifier_value: str,
        scope: Mapping[str, Any],
        effective_start: str | None = None,
        effective_end: str | None = None,
        provenance_refs: Iterable[str],
        validate_after_registration: bool = True,
    ) -> dict[str, Any]:
        """Attach accepted identity evidence to an existing durable decision.

        External values are lookup evidence only. They never participate in
        subject UUID allocation and cannot create a decision through this API.
        """
        if subject_type not in SUBJECT_TYPES:
            raise ValueError(f"unsupported subject type: {subject_type}")
        if not authority or not identifier_type or not identifier_value:
            raise ValueError("authority, identifier type and value are required")
        normalized_scope = {str(key): value for key, value in dict(scope).items() if value is not None}
        if not normalized_scope:
            raise ValueError("identity crosswalk requires non-empty scope")
        if effective_start and effective_end and effective_end < effective_start:
            raise ValueError("identity crosswalk interval ends before it starts")
        provenance = sorted({str(value) for value in provenance_refs if str(value).strip()})
        if not provenance:
            raise ValueError("accepted identity crosswalk requires provenance")
        self.install_identity_crosswalk_contract()
        metadata = self.metadata()
        scope_json = _canonical_json(normalized_scope)
        scope_sha256 = hashlib.sha256(scope_json.encode("utf-8")).hexdigest()
        crosswalk_identity = {
            "authority": authority,
            "effective_end": effective_end,
            "effective_start": effective_start,
            "identifier_type": identifier_type,
            "identifier_value": identifier_value,
            "scope_sha256": scope_sha256,
        }
        crosswalk_id = (
            "identity_crosswalk:"
            + hashlib.sha256(_canonical_json(crosswalk_identity).encode("utf-8")).hexdigest()
        )
        accepted_at = self._utc_now()
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            assignment = conn.execute(
                "SELECT * FROM identity_decision_assignment WHERE identity_decision_id=?",
                (identity_decision_id,),
            ).fetchone()
            if assignment is None:
                raise KeyError(f"unknown identity decision: {identity_decision_id}")
            if assignment["database_generation_id"] != metadata["database_generation_id"]:
                raise ValueError("identity decision belongs to another database generation")
            if (assignment["subject_type"], assignment["subject_id"]) != (subject_type, subject_id):
                raise ValueError("crosswalk subject differs from its accepted identity decision")
            existing = conn.execute(
                "SELECT * FROM accepted_identity_crosswalk WHERE crosswalk_id=?",
                (crosswalk_id,),
            ).fetchone()
            if existing is not None:
                existing_row = dict(existing)
                if (
                    existing_row["identity_decision_id"] != identity_decision_id
                    or existing_row["subject_type"] != subject_type
                    or existing_row["subject_id"] != subject_id
                ):
                    raise ValueError("accepted crosswalk conflicts with another identity")
                retained_provenance = sorted(
                    set(json.loads(existing_row["provenance_json"])) | set(provenance)
                )
                if retained_provenance != json.loads(existing_row["provenance_json"]):
                    existing_row["provenance_json"] = _canonical_json(retained_provenance)
                    conn.execute(
                        "UPDATE accepted_identity_crosswalk SET provenance_json=? "
                        "WHERE crosswalk_id=?",
                        (existing_row["provenance_json"], crosswalk_id),
                    )
                    conn.commit()
                else:
                    conn.rollback()
                return existing_row
            candidates = conn.execute(
                """
                SELECT subject_type,subject_id,effective_start,effective_end
                FROM accepted_identity_crosswalk
                WHERE authority=? AND identifier_type=? AND identifier_value=?
                  AND scope_sha256=?
                """,
                (authority, identifier_type, identifier_value, scope_sha256),
            ).fetchall()
            for candidate in candidates:
                if (candidate["subject_type"], candidate["subject_id"]) != (subject_type, subject_id) and self._intervals_overlap(
                    candidate["effective_start"], candidate["effective_end"], effective_start, effective_end
                ):
                    raise ValueError("one scoped identity crosswalk overlaps different subjects")
            row = {
                "crosswalk_id": crosswalk_id,
                "database_generation_id": metadata["database_generation_id"],
                "identity_decision_id": identity_decision_id,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "authority": authority,
                "identifier_type": identifier_type,
                "identifier_value": identifier_value,
                "scope_json": scope_json,
                "scope_sha256": scope_sha256,
                "effective_start": effective_start,
                "effective_end": effective_end,
                "provenance_json": _canonical_json(provenance),
                "accepted_at_utc": accepted_at,
            }
            conn.execute(
                "INSERT INTO accepted_identity_crosswalk VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                tuple(row.values()),
            )
            conn.commit()
        if validate_after_registration:
            self._validate_schema()
        return row

    def resolve_accepted_identity(
        self,
        crosswalk_candidates: Iterable[Mapping[str, Any]],
        *,
        effective_at: str | None = None,
    ) -> dict[str, Any]:
        """Resolve evidence-backed crosswalks to one existing durable identity."""
        candidates = [dict(row) for row in crosswalk_candidates]
        if not candidates:
            raise KeyError("no identity crosswalk candidates supplied")
        with self._connection() as conn:
            table = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                "AND name='accepted_identity_crosswalk'"
            ).fetchone()[0]
            if not table:
                raise KeyError("accepted identity crosswalk contract is not installed")
            matches: list[sqlite3.Row] = []
            for candidate in candidates:
                normalized_scope = {
                    str(key): value
                    for key, value in dict(candidate["scope"]).items()
                    if value is not None
                }
                if not normalized_scope:
                    raise ValueError("identity crosswalk requires non-empty scope")
                scope_json = _canonical_json(normalized_scope)
                scope_sha256 = hashlib.sha256(scope_json.encode("utf-8")).hexdigest()
                params: list[Any] = [
                    candidate["authority"], candidate["identifier_type"],
                    candidate["identifier_value"], scope_sha256,
                ]
                time_clause = ""
                if effective_at is not None:
                    time_clause = (
                        " AND (effective_start IS NULL OR effective_start<=?)"
                        " AND (effective_end IS NULL OR effective_end>=?)"
                    )
                    params.extend([effective_at, effective_at])
                matches.extend(conn.execute(
                    """
                    SELECT * FROM accepted_identity_crosswalk
                    WHERE authority=? AND identifier_type=? AND identifier_value=?
                      AND scope_sha256=?
                    """ + time_clause,
                    params,
                ).fetchall())
            unique = {(row["identity_decision_id"], row["subject_type"], row["subject_id"]) for row in matches}
            if not unique:
                raise KeyError("no accepted identity matches the supplied crosswalks")
            if len(unique) != 1:
                raise ValueError("accepted crosswalk candidates resolve to different identities")
            decision_id, subject_type, subject_id = next(iter(unique))
            assignment = conn.execute(
                "SELECT decision_json FROM identity_decision_assignment WHERE identity_decision_id=?",
                (decision_id,),
            ).fetchone()
        if assignment is None:
            raise ValueError("accepted crosswalk has no durable identity decision")
        decision = json.loads(assignment[0])
        return {
            **decision,
            "identity_decision_id": decision_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "matched_crosswalk_ids": sorted({row["crosswalk_id"] for row in matches}),
            "reuse_action": "reuse_existing_accepted_identity",
        }

    def accepted_identity_for_subject(
        self,
        *,
        subject_type: str,
        subject_id: str,
    ) -> dict[str, Any]:
        """Return the durable decision behind an already canonical subject."""
        if subject_type not in SUBJECT_TYPES:
            raise ValueError(f"unsupported subject type: {subject_type}")
        metadata = self.metadata()
        with self._connection() as conn:
            stored = conn.execute(
                """
                SELECT identity_decision_id,database_generation_id,decision_json
                FROM identity_decision_assignment
                WHERE subject_type=? AND subject_id=?
                """,
                (subject_type, subject_id),
            ).fetchone()
        if stored is None:
            raise KeyError(f"subject has no accepted identity decision: {subject_type} {subject_id}")
        if stored["database_generation_id"] != metadata["database_generation_id"]:
            raise ValueError("subject identity decision belongs to another database generation")
        return {
            **json.loads(stored["decision_json"]),
            "identity_decision_id": stored["identity_decision_id"],
            "subject_type": subject_type,
            "subject_id": subject_id,
            "installation_id": metadata["installation_id"],
            "database_generation_id": metadata["database_generation_id"],
        }

    def accepted_crosswalk_rows(self) -> list[dict[str, Any]]:
        with self._connection() as conn:
            table = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                "AND name='accepted_identity_crosswalk'"
            ).fetchone()[0]
            if not table:
                return []
            return [dict(row) for row in conn.execute(
                "SELECT * FROM accepted_identity_crosswalk ORDER BY crosswalk_id"
            )]

    def assignment_count(self) -> int:
        """Count assignments without loading and decoding every decision."""
        with self._connection() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM identity_decision_assignment").fetchone()[0])

    def rows(self) -> list[dict[str, Any]]:
        metadata = self.metadata()
        with self._connection() as conn:
            stored = conn.execute(
                "SELECT decision_json FROM identity_decision_assignment ORDER BY identity_decision_id"
            ).fetchall()
        rows = []
        for item in stored:
            row = json.loads(item[0])
            row["installation_id"] = metadata["installation_id"]
            row["database_generation_id"] = metadata["database_generation_id"]
            rows.append(row)
        return rows

    def import_or_verify(self, decisions: Iterable[Mapping[str, Any]]) -> None:
        incoming = [dict(row) for row in decisions]
        metadata = self.metadata()
        current = {row["identity_decision_id"]: row for row in self.rows()}
        if current:
            comparable = {
                key: {k: v for k, v in row.items() if k not in {"installation_id", "database_generation_id"}}
                for key, row in current.items()
            }
            normalized = {
                row["identity_decision_id"]: {k: v for k, v in row.items() if k not in {"installation_id", "database_generation_id"}}
                for row in incoming
            }
            if comparable != normalized:
                raise ValueError("incoming identity decisions conflict with durable installation state")
            return
        now = self._utc_now()
        with self._connection() as conn:
            for row in incoming:
                conn.execute(
                    "INSERT INTO identity_decision_assignment VALUES (?,?,?,?,?,?,?)",
                    (
                        row["identity_decision_id"], metadata["database_generation_id"],
                        row["subject_type"], row["subject_id"], row["allocation_action"],
                        _canonical_json({k: v for k, v in row.items() if k not in {"installation_id", "database_generation_id"}}),
                        now,
                    ),
                )
            conn.commit()
        self._validate_schema()

    def create_decision(
        self,
        *,
        subject_type: str,
        accepted_identity_statement: str,
        economic_object_type: str,
        existing_subject_id: str | None = None,
        provenance_refs: Iterable[str] = (),
        decision_attributes: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if subject_type not in SUBJECT_TYPES:
            raise ValueError(f"unsupported subject type: {subject_type}")
        metadata = self.metadata()
        row = {
            "identity_decision_id": _new_internal_id("identity_decision"),
            "decision_state": READY_STATE,
            "subject_type": subject_type,
            "subject_id": existing_subject_id or _new_internal_id(subject_type),
            "allocation_action": "reuse_existing" if existing_subject_id else "assign_new_internal_id",
            "accepted_identity_statement": accepted_identity_statement,
            "economic_object_type": economic_object_type,
            "decision_attributes": dict(decision_attributes or {}),
            "provenance_refs": sorted(set(provenance_refs)),
            "identity_inputs_excluded_from_subject_id": [
                "name", "exchange_code", "provider_record_id", "lifecycle_evidence_id",
                "isin", "effective_date", "source_document",
            ],
        }
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO identity_decision_assignment VALUES (?,?,?,?,?,?,?)",
                (
                    row["identity_decision_id"], metadata["database_generation_id"],
                    subject_type, row["subject_id"], row["allocation_action"],
                    _canonical_json(row), self._utc_now(),
                ),
            )
            conn.commit()
        return {**row, "installation_id": metadata["installation_id"], "database_generation_id": metadata["database_generation_id"]}

    def create_decisions_batch(
        self,
        decisions: Iterable[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """Allocate many accepted subjects in one durable transaction.

        This is the bulk counterpart of :meth:`create_decision`.  Subject and
        decision UUIDs remain installation-local random allocations; callers
        must perform any economic-object idempotency lookup before requesting
        new allocations.  A failure rolls the whole batch back so a snapshot
        build cannot observe a partially allocated population.
        """
        incoming = [dict(item) for item in decisions]
        metadata = self.metadata()
        rows: list[dict[str, Any]] = []
        for item in incoming:
            subject_type = item["subject_type"]
            if subject_type not in SUBJECT_TYPES:
                raise ValueError(f"unsupported subject type: {subject_type}")
            existing_subject_id = item.get("existing_subject_id")
            row = {
                "identity_decision_id": _new_internal_id("identity_decision"),
                "decision_state": READY_STATE,
                "subject_type": subject_type,
                "subject_id": existing_subject_id or _new_internal_id(subject_type),
                "allocation_action": "reuse_existing" if existing_subject_id else "assign_new_internal_id",
                "accepted_identity_statement": item["accepted_identity_statement"],
                "economic_object_type": item["economic_object_type"],
                "decision_attributes": dict(item.get("decision_attributes") or {}),
                "provenance_refs": sorted(set(item.get("provenance_refs") or ())),
                "identity_inputs_excluded_from_subject_id": [
                    "name", "exchange_code", "provider_record_id", "lifecycle_evidence_id",
                    "isin", "effective_date", "source_document",
                ],
            }
            rows.append(row)
        now = self._utc_now()
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany(
                "INSERT INTO identity_decision_assignment VALUES (?,?,?,?,?,?,?)",
                [
                    (
                        row["identity_decision_id"], metadata["database_generation_id"],
                        row["subject_type"], row["subject_id"], row["allocation_action"],
                        _canonical_json(row), now,
                    )
                    for row in rows
                ],
            )
            conn.commit()
        self._validate_schema()
        return [
            {**row, "installation_id": metadata["installation_id"], "database_generation_id": metadata["database_generation_id"]}
            for row in rows
        ]

    def normalize_legacy_assignments(
        self,
        legacy_assignments: Mapping[str, str],
        *,
        migration_id: str,
    ) -> list[dict[str, Any]]:
        """One-time, generation-preserving normalization of grandfathered IDs.

        ``legacy_assignments`` maps an already accepted identity decision to its
        exact current legacy subject ID.  The economic decision and database
        generation are immutable; only the canonical subject token changes to
        a newly assigned opaque UUID.  The old ID is retained in the migration
        audit as provenance and must be represented as an alias by the caller.
        """
        if not migration_id or any(ch.isspace() for ch in migration_id):
            raise ValueError("migration_id must be a non-empty path-safe token")
        requested = dict(legacy_assignments)
        if not requested:
            return []
        metadata = self.metadata()
        migrated_at = self._utc_now()
        results: list[dict[str, Any]] = []
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS identity_assignment_migration (
                    identity_decision_id TEXT PRIMARY KEY,
                    database_generation_id TEXT NOT NULL,
                    migration_id TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    old_subject_id TEXT NOT NULL UNIQUE,
                    new_subject_id TEXT NOT NULL UNIQUE,
                    migrated_at_utc TEXT NOT NULL,
                    FOREIGN KEY(identity_decision_id)
                        REFERENCES identity_decision_assignment(identity_decision_id)
                )
                """
            )
            for decision_id, expected_old_id in sorted(requested.items()):
                existing_migration = conn.execute(
                    "SELECT * FROM identity_assignment_migration WHERE identity_decision_id=?",
                    (decision_id,),
                ).fetchone()
                if existing_migration is not None:
                    row = dict(existing_migration)
                    if row["old_subject_id"] != expected_old_id or row["migration_id"] != migration_id:
                        raise ValueError(f"identity decision already normalized by another operation: {decision_id}")
                    results.append(row)
                    continue
                stored = conn.execute(
                    "SELECT * FROM identity_decision_assignment WHERE identity_decision_id=?",
                    (decision_id,),
                ).fetchone()
                if stored is None:
                    raise KeyError(f"unknown identity decision: {decision_id}")
                if stored["database_generation_id"] != metadata["database_generation_id"]:
                    raise ValueError("identity assignment belongs to another database generation")
                if stored["allocation_action"] != "reuse_existing":
                    raise ValueError(f"only grandfathered reuse_existing decisions may be normalized: {decision_id}")
                if stored["subject_id"] != expected_old_id:
                    raise ValueError(f"legacy subject precondition failed: {decision_id}")
                subject_type = str(stored["subject_type"])
                if subject_type not in SUBJECT_TYPES:
                    raise ValueError(
                        f"compatibility-only subject cannot receive a normalized durable ID: {subject_type}"
                    )
                opaque_prefix = f"{subject_type}:"
                opaque_suffix = expected_old_id[len(opaque_prefix):] if expected_old_id.startswith(opaque_prefix) else ""
                if len(opaque_suffix) == 32 and all(ch in "0123456789abcdef" for ch in opaque_suffix):
                    raise ValueError(f"assignment is already opaque: {decision_id}")
                new_subject_id = _new_internal_id(subject_type)
                decision = json.loads(stored["decision_json"])
                if decision.get("subject_id") != expected_old_id:
                    raise ValueError(f"decision JSON subject precondition failed: {decision_id}")
                decision["subject_id"] = new_subject_id
                decision["allocation_action"] = "normalized_legacy_assignment"
                attrs = dict(decision.get("decision_attributes") or {})
                attrs["legacy_subject_id"] = expected_old_id
                attrs["legacy_normalization_migration_id"] = migration_id
                decision["decision_attributes"] = attrs
                conn.execute(
                    """
                    UPDATE identity_decision_assignment
                    SET subject_id=?, allocation_action=?, decision_json=?
                    WHERE identity_decision_id=?
                    """,
                    (new_subject_id, "normalized_legacy_assignment", _canonical_json(decision), decision_id),
                )
                crosswalk_table_present = conn.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                    "AND name='accepted_identity_crosswalk'"
                ).fetchone()[0]
                if crosswalk_table_present:
                    conn.execute(
                        "UPDATE accepted_identity_crosswalk SET subject_id=? "
                        "WHERE identity_decision_id=?",
                        (new_subject_id, decision_id),
                    )
                audit = {
                    "identity_decision_id": decision_id,
                    "database_generation_id": metadata["database_generation_id"],
                    "migration_id": migration_id,
                    "subject_type": subject_type,
                    "old_subject_id": expected_old_id,
                    "new_subject_id": new_subject_id,
                    "migrated_at_utc": migrated_at,
                }
                conn.execute(
                    "INSERT INTO identity_assignment_migration VALUES (?,?,?,?,?,?,?)",
                    tuple(audit[key] for key in (
                        "identity_decision_id", "database_generation_id", "migration_id",
                        "subject_type", "old_subject_id", "new_subject_id", "migrated_at_utc",
                    )),
                )
                results.append(audit)
            conn.commit()
        self._validate_schema()
        return results

    def assignment_migrations(self) -> list[dict[str, Any]]:
        with self._connection() as conn:
            present = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='identity_assignment_migration'"
            ).fetchone()[0]
            if not present:
                return []
            return [dict(row) for row in conn.execute(
                "SELECT * FROM identity_assignment_migration ORDER BY identity_decision_id"
            )]

    def backup(self) -> Path:
        return self.backup_to(self.backup_root)

    def backup_to(self, target_root: Path) -> Path:
        """Write a transactionally consistent generation-scoped backup/mirror."""
        metadata = self.metadata()
        generation_segment = metadata["database_generation_id"].split(":", 1)[-1]
        target = target_root / generation_segment / self.path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(target.suffix + ".partial")
        if temp.exists():
            temp.unlink()
        source_conn = self._connect()
        backup_conn = sqlite3.connect(temp)
        try:
            source_conn.backup(backup_conn)
            backup_conn.commit()
        finally:
            backup_conn.close()
            source_conn.close()
        os.replace(temp, target)
        return target

    @classmethod
    def recover_from_backup(cls, path: Path, backup_root: Path, backup_path: Path) -> "InstallationIdentityState":
        backup = cls(backup_path, backup_root)
        metadata = backup.metadata()
        path.parent.mkdir(parents=True, exist_ok=True)
        source_conn = sqlite3.connect(backup_path)
        target_conn = sqlite3.connect(path)
        try:
            source_conn.backup(target_conn)
            target_conn.commit()
        finally:
            target_conn.close()
            source_conn.close()
        recovered = cls(path, backup_root)
        if recovered.metadata()["database_generation_id"] != metadata["database_generation_id"]:
            raise AssertionError("recovered identity generation changed")
        return recovered

    def reset_database_generation(self, *, expected_generation_id: str, allow_destructive_reset: bool) -> "InstallationIdentityState":
        metadata = self.metadata()
        if not allow_destructive_reset or expected_generation_id != metadata["database_generation_id"]:
            raise PermissionError("explicit matching-generation destructive reset authorization is required")
        new_generation_id = _new_internal_id("database_generation")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            locked_metadata = conn.execute(
                "SELECT * FROM identity_state_metadata WHERE singleton_id=1"
            ).fetchone()
            if locked_metadata is None:
                raise ValueError("identity state metadata is missing")
            if locked_metadata["database_generation_id"] != expected_generation_id:
                raise PermissionError("identity database generation changed before reset")
            # The write reservation prevents another assignment commit between
            # this verified old-generation backup and the destructive reset.
            self.backup()
            migration_table_present = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='identity_assignment_migration'"
            ).fetchone()[0]
            if migration_table_present:
                conn.execute("DELETE FROM identity_assignment_migration")
            crosswalk_table_present = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                "AND name='accepted_identity_crosswalk'"
            ).fetchone()[0]
            if crosswalk_table_present:
                conn.execute("DELETE FROM accepted_identity_crosswalk")
            conn.execute("DELETE FROM identity_decision_assignment")
            conn.execute(
                """
                UPDATE identity_state_metadata
                SET database_generation_id=?, created_at_utc=?
                WHERE singleton_id=1
                """,
                (new_generation_id, self._utc_now()),
            )
            conn.commit()
        reset = InstallationIdentityState(self.path, self.backup_root)
        reset_metadata = reset.metadata()
        if reset_metadata["installation_id"] != metadata["installation_id"]:
            raise AssertionError("database-generation reset changed installation identity")
        if reset_metadata["database_generation_id"] != new_generation_id:
            raise AssertionError("database-generation reset did not publish the allocated generation")
        if reset.rows() or reset.assignment_migrations() or reset.accepted_crosswalk_rows():
            raise AssertionError("new database generation retained abandoned assignments")
        return reset
