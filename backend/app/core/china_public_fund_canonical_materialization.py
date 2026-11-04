"""Canonical China Public Fund row materialization and retained-history helpers.

The historical inputs are concatenated gzip streams: every successful provider
partition was appended as its own gzip member.  This module exposes the member
boundary as the recovery unit. The canonical row builders are also the active
Fund update owner and map observations only through accepted identity evidence.

Provider codes are lookup evidence.  They never allocate or define a subject.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


NAV_ROUTE = "eastmoney_pingzhongdata_js"
TRADING_ROUTE = "sina_fund_etf_hist_klc2"
DATASET_NAME = "china_public_fund_historical_canonical"
DATASET_ID = "dataset:china_public_fund_historical_canonical_v1"
DOMAIN = "funds_etfs"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_key(namespace: str, value: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(dict(value)).encode("utf-8")).hexdigest()
    return f"{namespace}:{digest}"


def sha256_file(path: Path, *, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".partial", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


@dataclass(frozen=True)
class GzipMember:
    index: int
    compressed_start: int
    compressed_end: int
    payload: bytes


def iter_concatenated_gzip_members(
    path: Path,
    *,
    start_offset: int = 0,
    start_index: int = 0,
    block_size: int = 4 * 1024 * 1024,
) -> Iterator[GzipMember]:
    """Yield exact gzip members without reading bytes before ``start_offset``.

    ``gzip.GzipFile`` deliberately concatenates members and therefore cannot
    expose a durable recovery boundary.  zlib's ``unused_data`` identifies the
    exact next-member offset even when the underlying read crosses a boundary.
    """
    size = path.stat().st_size
    if start_offset < 0 or start_offset > size:
        raise ValueError("gzip resume offset is outside the file")
    if start_offset == size:
        return
    with path.open("rb") as handle:
        handle.seek(start_offset)
        member_index = start_index
        while handle.tell() < size:
            member_start = handle.tell()
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
            decoded: list[bytes] = []
            while not decoder.eof:
                chunk = handle.read(block_size)
                if not chunk:
                    raise EOFError(f"truncated gzip member at compressed offset {member_start}")
                output = decoder.decompress(chunk)
                if output:
                    decoded.append(output)
                if decoder.eof:
                    member_end = handle.tell() - len(decoder.unused_data)
                    handle.seek(member_end)
                    break
            yield GzipMember(
                index=member_index,
                compressed_start=member_start,
                compressed_end=member_end,
                payload=b"".join(decoded),
            )
            member_index += 1


def decode_member_rows(member: GzipMember) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(member.payload.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"invalid NDJSON in gzip member {member.index}, line {number}"
            ) from exc
    return rows


@dataclass(frozen=True)
class FundTarget:
    route: str
    code: str
    subject_type: str
    subject_id: str
    identity_decision_id: str
    fund_subject_id: str
    csrc_eid_fund_id: str
    effective_start: str | None
    effective_end: str | None
    evidence_refs: tuple[str, ...]
    mapping_basis: str

    def disposition(self, observation_date: str) -> tuple[str, str]:
        if self.effective_start and observation_date < self.effective_start:
            return "unresolved", "observation_precedes_proved_owner_lifecycle"
        if self.effective_end and self.effective_end != "9999-12-31" and observation_date > self.effective_end:
            return "unresolved", "observation_follows_proved_owner_lifecycle"
        return "canonical", "accepted_identity_and_effective_interval"


def validate_member_pair(
    source_rows: Sequence[Mapping[str, Any]],
    fact_rows: Sequence[Mapping[str, Any]],
) -> str | None:
    if len(source_rows) != len(fact_rows):
        raise ValueError("source/fact gzip members contain different row counts")
    partition_id: str | None = None
    for index, (source, fact) in enumerate(zip(source_rows, fact_rows)):
        source_partition = str(source.get("materialized_partition_id") or "")
        fact_partition = f"{source.get('exact_callable_or_route')}|{source.get('provider_native_symbol')}"
        if source_partition != fact_partition:
            raise ValueError(f"source partition identity is inconsistent at member row {index}")
        if partition_id is None:
            partition_id = source_partition
        elif source_partition != partition_id:
            raise ValueError("one gzip member contains multiple provider partitions")
        comparable = (
            "source_observation_key",
            "metric_id",
            "observation_date",
            "provider_native_symbol",
        )
        for field in comparable:
            if source.get(field) != fact.get(field):
                raise ValueError(f"source/fact member mismatch for {field} at row {index}")
    return partition_id


def source_observation_key(row: Mapping[str, Any], target: FundTarget) -> str:
    return stable_key(
        "source_observation",
        {
            "actual_upstream_owner": row["actual_upstream_owner"],
            "exact_callable_or_route": row["exact_callable_or_route"],
            "metric_id": row["metric_id"],
            "observation_date": row["observation_date"],
            "provider_native_symbol": row["provider_native_symbol"],
            "source_version_scope": row["source_version_scope"],
            "subject_id": target.subject_id,
            "subject_type": target.subject_type,
        },
    )


def logical_fact_key(row: Mapping[str, Any], target: FundTarget) -> str:
    return stable_key(
        "logical_fact",
        {
            "economic_time": {
                "primary_role": row["time_role"],
                "primary_value": row["observation_date"],
            },
            "fact_dimensions": {},
            "metric_id": row["metric_id"],
            "subject": {"subject_id": target.subject_id, "subject_type": target.subject_type},
            "unit": row["canonical_unit"],
            "currency": row["canonical_currency"],
            "scale": row["canonical_scale"],
            "version_effective_scope": {
                "source_version_scope": row["fact_version_scope"],
            },
        },
    )


def logical_fact_base_key(row: Mapping[str, Any], target: FundTarget) -> str:
    return stable_key(
        "logical_fact_base",
        {
            "economic_time": {
                "primary_role": row["time_role"],
                "primary_value": row["observation_date"],
            },
            "fact_dimensions": {},
            "metric_id": row["metric_id"],
            "subject": {"subject_id": target.subject_id, "subject_type": target.subject_type},
        },
    )


def canonical_source_row(
    row: Mapping[str, Any],
    *,
    target: FundTarget,
    series_id: str,
    processed_at_utc: str,
) -> dict[str, Any]:
    key = source_observation_key(row, target)
    raw_value = row.get("native_value")
    trace = {
        "canonical_subject_id": target.subject_id,
        "canonical_subject_type": target.subject_type,
        "canonical_series_id": series_id,
        "identity_decision_id": target.identity_decision_id,
        "legacy_source_observation_key": row.get("source_observation_key"),
        "legacy_subject_id": row.get("subject_id"),
        "mapping_basis": target.mapping_basis,
        "provenance_refs": list(target.evidence_refs),
        "retained_candidate_id": row.get("candidate_id"),
        "source_lineage": row.get("lineage"),
    }
    record_material = {
        "metric_id": row["metric_id"],
        "native_field": row.get("native_field"),
        "native_value": raw_value,
        "observation_date": row["observation_date"],
        "provider_native_symbol": row["provider_native_symbol"],
        "response_content_hash": row.get("response_content_hash"),
        "source_version_scope": row.get("source_version_scope"),
    }
    year = int(str(row["observation_date"])[:4])
    return {
        "source_observation_key": key,
        "source_observation_base_key": stable_key(
            "source_observation_base",
            {
                "route": row["exact_callable_or_route"],
                "metric_id": row["metric_id"],
                "observation_date": row["observation_date"],
                "subject_id": target.subject_id,
            },
        ),
        "metric_id": str(row["metric_id"]),
        "record_hash": hashlib.sha256(canonical_json(record_material).encode("utf-8")).hexdigest(),
        "domain": DOMAIN,
        "dataset_name": DATASET_NAME,
        "entity_key": target.subject_id,
        "subject_candidate": canonical_json(
            {"subject_id": target.subject_id, "subject_type": target.subject_type, "series_id": series_id}
        ),
        "event_date_or_period": str(row["observation_date"]),
        "partition_year": year,
        "source_provider": str(row["actual_upstream_owner"]),
        "source_interface": str(row["exact_callable_or_route"]),
        "source_symbol": str(row["provider_native_symbol"]),
        "source_field_locator": str(row.get("native_field") or ""),
        "raw_value_json": canonical_json(raw_value),
        "raw_unit": str(row.get("native_unit") or ""),
        "raw_currency": str(row.get("native_currency") or ""),
        "raw_scale": str(row.get("native_scale") or ""),
        "source_trace_json": canonical_json(trace),
        "source_record_json": canonical_json(record_material),
        "first_seen_at_utc": processed_at_utc,
        "source_detail_semantic_state": "canonical_standard_fact_source",
        "key_bucket": int(key.rsplit(":", 1)[-1][:2], 16),
        "source_partition_locator": "__FINAL_LOCATOR_PENDING__",
    }


def canonical_fact_row(
    row: Mapping[str, Any],
    *,
    target: FundTarget,
    series_id: str,
    canonical_source_key: str,
) -> dict[str, Any]:
    key = logical_fact_key(row, target)
    base_key = logical_fact_base_key(row, target)
    trace = {
        "identity_decision_id": target.identity_decision_id,
        "legacy_logical_fact_key": row.get("logical_fact_key"),
        "legacy_source_observation_key": row.get("source_observation_key"),
        "legacy_subject_id": row.get("subject_id"),
        "mapping_basis": target.mapping_basis,
        "provenance_refs": list(target.evidence_refs),
        "retained_candidate_id": row.get("candidate_id"),
    }
    normalization = {
        "canonical_unit_type": row.get("canonical_unit_type"),
        "direct_or_derived": row.get("direct_or_derived"),
        "semantic_basis": row.get("semantic_basis"),
        "transformation": "identity_rekey_only_value_unchanged",
    }
    year = int(str(row["observation_date"])[:4])
    result = {
        "logical_fact_key": key,
        "logical_fact_base_key": base_key,
        "record_hash": "",
        "dataset_name": DATASET_NAME,
        "dataset_id": DATASET_ID,
        "source_family": str((row.get("semantic_basis") or "").rsplit(" from ", 1)[-1]),
        "metric_id": str(row["metric_id"]),
        "subject_type": target.subject_type,
        "subject_id": target.subject_id,
        "series_id": series_id,
        "economic_time": str(row["observation_date"]),
        "primary_time_role": str(row["time_role"]),
        "fact_dimensions_json": "{}",
        "series_dimensions_json": "{}",
        "version_effective_scope_json": canonical_json(
            {"source_version_scope": row.get("fact_version_scope")}
        ),
        "normalized_value": str(row.get("fact_value")),
        "canonical_unit": str(row.get("canonical_unit") or ""),
        "canonical_currency": str(row.get("canonical_currency") or ""),
        "canonical_scale": str(row.get("canonical_scale") or ""),
        "normalization_evidence_json": canonical_json(normalization),
        "source_trace_json": canonical_json(trace),
        "direct_rank": 0,
        "classification": "accepted_direct_source_fact",
        "year": year,
        "source_observation_key": canonical_source_key,
        "source_domain": DOMAIN,
        "source_partition_year": year,
        "source_subject_hash_bucket": int(hashlib.sha256(target.subject_id.encode()).hexdigest()[:2], 16),
        "domain": DOMAIN,
        "partition_year": year,
        "fact_partition_locator": "__FINAL_LOCATOR_PENDING__",
    }
    result["record_hash"] = hashlib.sha256(
        canonical_json({key: value for key, value in result.items() if key not in {"record_hash", "fact_partition_locator"}}).encode("utf-8")
    ).hexdigest()
    return result


def unresolved_pair_row(
    source: Mapping[str, Any],
    fact: Mapping[str, Any],
    *,
    reason: str,
    target: FundTarget | None,
) -> dict[str, Any]:
    return {
        "provider_route": str(source.get("exact_callable_or_route") or ""),
        "provider_code": str(source.get("provider_native_symbol") or ""),
        "observation_date": str(source.get("observation_date") or ""),
        "metric_id": str(source.get("metric_id") or ""),
        "unresolved_reason": reason,
        "candidate_subject_type": target.subject_type if target else None,
        "candidate_subject_id": target.subject_id if target else None,
        "candidate_identity_decision_id": target.identity_decision_id if target else None,
        "legacy_source_observation_key": source.get("source_observation_key"),
        "legacy_logical_fact_key": fact.get("logical_fact_key"),
        "source_row_json": canonical_json(dict(source)),
        "fact_row_json": canonical_json(dict(fact)),
    }


def choose_bucket_count(row_count: int, *, target_rows: int = 1_500_000) -> int:
    if row_count <= 3_000_000:
        return 1
    needed = max(2, (row_count + target_rows - 1) // target_rows)
    bucket = 1
    while bucket < needed and bucket < 32:
        bucket *= 2
    return bucket


def subject_bucket(subject_id: str, bucket_count: int) -> int:
    if bucket_count <= 1:
        return 0
    return int(hashlib.sha256(subject_id.encode("utf-8")).hexdigest()[:8], 16) % bucket_count


def checkpoint_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=FULL;
        CREATE TABLE IF NOT EXISTS input_member_checkpoint(
            member_index INTEGER PRIMARY KEY,
            source_start INTEGER NOT NULL,
            source_end INTEGER NOT NULL UNIQUE,
            fact_start INTEGER NOT NULL,
            fact_end INTEGER NOT NULL UNIQUE,
            partition_id TEXT,
            route TEXT,
            provider_code TEXT,
            input_rows INTEGER NOT NULL,
            accepted_rows INTEGER NOT NULL,
            unresolved_rows INTEGER NOT NULL,
            source_fragment_path TEXT,
            source_fragment_sha256 TEXT,
            source_fragment_bytes INTEGER NOT NULL,
            fact_fragment_path TEXT,
            fact_fragment_sha256 TEXT,
            fact_fragment_bytes INTEGER NOT NULL,
            unresolved_fragment_path TEXT,
            unresolved_fragment_sha256 TEXT,
            unresolved_fragment_bytes INTEGER NOT NULL,
            min_date TEXT,
            max_date TEXT,
            completed_at_utc TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS fragment_group_summary(
            member_index INTEGER NOT NULL,
            layer_name TEXT NOT NULL,
            metric_id TEXT NOT NULL,
            partition_year INTEGER NOT NULL,
            subject_type TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            min_date TEXT NOT NULL,
            max_date TEXT NOT NULL,
            PRIMARY KEY(member_index,layer_name,metric_id,partition_year,subject_id)
        );
        CREATE INDEX IF NOT EXISTS idx_fragment_group_partition
            ON fragment_group_summary(layer_name,metric_id,partition_year);
        """
    )


def checkpoint_resume(connection: sqlite3.Connection) -> dict[str, int]:
    checkpoint_schema(connection)
    row = connection.execute(
        """
        SELECT member_index,source_end,fact_end
        FROM input_member_checkpoint ORDER BY member_index DESC LIMIT 1
        """
    ).fetchone()
    if row is None:
        return {"member_index": 0, "source_offset": 0, "fact_offset": 0}
    return {
        "member_index": int(row[0]) + 1,
        "source_offset": int(row[1]),
        "fact_offset": int(row[2]),
    }


def grouped_rows(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, int, str, str], list[int]]:
    grouped: dict[tuple[str, int, str, str], list[int]] = {}
    for index, row in enumerate(rows):
        key = (
            str(row["metric_id"]),
            int(row["partition_year"]),
            str(row.get("subject_type") or json.loads(str(row["subject_candidate"]))["subject_type"]),
            str(row.get("subject_id") or json.loads(str(row["subject_candidate"]))["subject_id"]),
        )
        grouped.setdefault(key, []).append(index)
    return grouped


def manifest_partition_path(
    *, layer_name: str, metric_id: str, year: int, bucket_count: int, bucket: int
) -> str:
    metric_token = metric_id.replace(".", "_")
    base = f"{layer_name}/domain={DOMAIN}/metric={metric_token}/year={year:04d}"
    if bucket_count > 1:
        base += f"/subject_hash_bucket={bucket:02d}-of-{bucket_count:02d}"
    return base + "/part-0.parquet"


def locator_id(
    *, snapshot_id: str, layer_name: str, subject_type: str, subject_id: str,
    metric_id: str, year: int, relative_path: str, row_group: int,
) -> str:
    return stable_key(
        "subject_partition_locator",
        {
            "snapshot_id": snapshot_id,
            "layer_name": layer_name,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "metric_id": metric_id,
            "year": year,
            "relative_path": relative_path,
            "row_group": row_group,
        },
    )
