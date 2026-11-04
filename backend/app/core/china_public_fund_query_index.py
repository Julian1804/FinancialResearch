"""Write-side owner for the China Public Fund query accelerators.

These tables are derived snapshot materializations. Query services may require
and read them, but ordinary reads must never create or rebuild them.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import unicodedata
from typing import Any, Iterable, Mapping

from backend.app.core.artifact_io import canonical_json


FUND_DOMAIN = "funds_etfs"  # Physical compatibility name only.
SEARCHABLE_TYPES = ("fund", "fund_share_class", "instrument", "listing", "entity")


def normalize_search_term(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.strip().split())


def _stable_id(prefix: str, value: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(dict(value)).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def ensure_fund_query_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS fund_search_index(
          search_record_id TEXT PRIMARY KEY,
          snapshot_id TEXT NOT NULL,
          normalized_term TEXT NOT NULL,
          display_value TEXT NOT NULL,
          match_kind TEXT NOT NULL,
          alias_type TEXT,
          subject_type TEXT NOT NULL,
          subject_id TEXT NOT NULL,
          canonical_name TEXT,
          effective_start TEXT,
          effective_end TEXT,
          scope_json TEXT NOT NULL,
          provenance_json TEXT NOT NULL
        )"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_fund_search_term ON fund_search_index(snapshot_id,normalized_term,subject_type)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_fund_search_subject ON fund_search_index(snapshot_id,subject_type,subject_id)"
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS fund_nonpromoted_interval_index(
          record_id TEXT PRIMARY KEY,
          snapshot_id TEXT NOT NULL,
          subject_type TEXT,
          subject_id TEXT,
          external_code TEXT,
          metric_id TEXT,
          time_start TEXT,
          time_end TEXT,
          row_count INTEGER,
          reason TEXT NOT NULL,
          evidence_json TEXT NOT NULL
        )"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_fund_nonpromoted_subject ON fund_nonpromoted_interval_index(snapshot_id,subject_type,subject_id,metric_id,time_start,time_end)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_fund_nonpromoted_code ON fund_nonpromoted_interval_index(snapshot_id,external_code,metric_id,time_start,time_end)"
    )


def rebuild_fund_search_index(connection: sqlite3.Connection, snapshot_id: str) -> int:
    """Build a snapshot-derived search accelerator without creating identity."""
    ensure_fund_query_schema(connection)
    connection.row_factory = sqlite3.Row
    subjects = {
        (str(row["subject_type"]), str(row["subject_id"])): dict(row)
        for row in connection.execute(
            "SELECT * FROM subject_registry WHERE domain=? AND subject_type IN (?,?,?,?,?)",
            (FUND_DOMAIN, *SEARCHABLE_TYPES),
        )
    }
    canonical_names: dict[tuple[str, str], str | None] = {}
    for key, row in subjects.items():
        attributes = json.loads(row["attributes_json"])
        canonical_names[key] = attributes.get("display_name") or None
    connection.execute("DELETE FROM fund_search_index")
    records: dict[str, tuple[Any, ...]] = {}

    def add(
        *, subject_type: str, subject_id: str, display_value: str,
        match_kind: str, alias_type: str | None, effective_start: str | None,
        effective_end: str | None, scope_json: str, provenance_json: str,
    ) -> None:
        term = normalize_search_term(display_value)
        if not term:
            return
        identity = {
            "snapshot_id": snapshot_id, "normalized_term": term,
            "match_kind": match_kind, "alias_type": alias_type,
            "subject_type": subject_type, "subject_id": subject_id,
            "effective_start": effective_start, "effective_end": effective_end,
            "scope_json": scope_json,
        }
        record_id = _stable_id("fund_search", identity)
        records[record_id] = (
            record_id, snapshot_id, term, display_value, match_kind, alias_type,
            subject_type, subject_id, canonical_names.get((subject_type, subject_id)),
            effective_start, effective_end, scope_json, provenance_json,
        )

    for (subject_type, subject_id), row in subjects.items():
        name = canonical_names[(subject_type, subject_id)]
        if name:
            add(
                subject_type=subject_type, subject_id=subject_id, display_value=name,
                match_kind="canonical_name", alias_type=None,
                effective_start=row["effective_start"], effective_end=row["effective_end"],
                scope_json=canonical_json({"universe": "Fund", "jurisdiction": "CN"}),
                provenance_json=canonical_json(["subject_registry.attributes_json.display_name"]),
            )
    for row in connection.execute(
        "SELECT * FROM subject_alias_registry WHERE acceptance_status='accepted' ORDER BY alias_id"
    ):
        key = (str(row["subject_type"]), str(row["subject_id"]))
        if key not in subjects:
            continue
        add(
            subject_type=key[0], subject_id=key[1], display_value=str(row["alias_value"]),
            match_kind="accepted_alias", alias_type=str(row["alias_type"]),
            effective_start=row["effective_start"], effective_end=row["effective_end"],
            scope_json=str(row["scope_json"]), provenance_json=str(row["provenance_json"]),
        )
    connection.executemany(
        "INSERT INTO fund_search_index VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [records[key] for key in sorted(records)],
    )
    return len(records)


def write_fund_search_delta(
    connection: sqlite3.Connection,
    snapshot_id: str,
    subjects: Iterable[Mapping[str, Any]],
    aliases: Iterable[Mapping[str, Any]],
) -> int:
    """Write search rows only for subjects changed in one control delta."""
    ensure_fund_query_schema(connection)
    subject_rows = {
        (str(row["subject_type"]), str(row["subject_id"])): dict(row)
        for row in subjects if row.get("domain") == FUND_DOMAIN
        and row.get("subject_type") in SEARCHABLE_TYPES
    }
    records: dict[str, tuple[Any, ...]] = {}

    def add(row: Mapping[str, Any], value: str, match_kind: str, alias_type: str | None,
            effective_start: str | None, effective_end: str | None,
            scope_json: str, provenance_json: str) -> None:
        term = normalize_search_term(value)
        if not term:
            return
        identity = {
            "snapshot_id": snapshot_id, "normalized_term": term,
            "match_kind": match_kind, "alias_type": alias_type,
            "subject_type": row["subject_type"], "subject_id": row["subject_id"],
            "effective_start": effective_start, "effective_end": effective_end,
            "scope_json": scope_json,
        }
        record_id = _stable_id("fund_search", identity)
        canonical_name = json.loads(row["attributes_json"]).get("display_name")
        records[record_id] = (
            record_id, snapshot_id, term, value, match_kind, alias_type,
            row["subject_type"], row["subject_id"], canonical_name,
            effective_start, effective_end, scope_json, provenance_json,
        )

    for row in subject_rows.values():
        name = json.loads(row["attributes_json"]).get("display_name")
        if name:
            add(
                row, str(name), "canonical_name", None,
                row.get("effective_start"), row.get("effective_end"),
                canonical_json({"universe": "Fund", "jurisdiction": "CN"}),
                canonical_json(["subject_registry.attributes_json.display_name"]),
            )
    for alias in aliases:
        key = (str(alias["subject_type"]), str(alias["subject_id"]))
        subject = subject_rows.get(key)
        if subject and alias.get("acceptance_status") == "accepted":
            add(
                subject, str(alias["alias_value"]), "accepted_alias",
                str(alias["alias_type"]), alias.get("effective_start"),
                alias.get("effective_end"), str(alias["scope_json"]),
                str(alias["provenance_json"]),
            )
    connection.executemany(
        "INSERT INTO fund_search_index VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [records[key] for key in sorted(records)],
    )
    return len(records)


def replace_nonpromoted_interval_index(
    connection: sqlite3.Connection,
    snapshot_id: str,
    records: Iterable[Mapping[str, Any]],
) -> int:
    ensure_fund_query_schema(connection)
    connection.execute("DELETE FROM fund_nonpromoted_interval_index")
    rows = []
    for source in records:
        row = dict(source)
        identity = {
            key: row.get(key)
            for key in (
                "snapshot_id", "subject_type", "subject_id", "external_code",
                "metric_id", "time_start", "time_end", "reason",
            )
        }
        identity["snapshot_id"] = snapshot_id
        rows.append((
            _stable_id("fund_nonpromoted_interval", identity), snapshot_id,
            row.get("subject_type"), row.get("subject_id"), row.get("external_code"),
            row.get("metric_id"), row.get("time_start"), row.get("time_end"),
            row.get("row_count"), str(row["reason"]),
            canonical_json(list(row.get("evidence_refs", []))),
        ))
    connection.executemany(
        "INSERT INTO fund_nonpromoted_interval_index VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows
    )
    return len(rows)
