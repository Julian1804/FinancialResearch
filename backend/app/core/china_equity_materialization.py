from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import threading
from contextlib import closing
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import duckdb


ROOT = Path(__file__).resolve().parents[3]

_BUCKET_CONNECTION: duckdb.DuckDBPyConnection | None = None
_BUCKET_CONNECTION_LOCK = threading.Lock()

from backend.app.core.china_equity_foundation import (  # noqa: E402
    ChinaEquitySubjectBinding,
    AcceptedChinaEquityEpisodeIndex,
    canonical_financial_metric,
    canonical_json,
    current_foundation_state,
    derive_coverage_state,
    financial_logical_fact_key,
    financial_series_object_key,
    relationship_id,
    sha256_file,
    stable_key,
    utc_now,
    write_json_atomic,
)
from backend.app.core.snapshot_manifest import clone_snapshot_from_manifest, reconcile_manifest_aggregate_counts
from backend.app.core.china_equity_source_semantics import (  # noqa: E402
    DAILY_METRIC_CONTRACT,
    derive_coverage_from_route_evidence,
    require_internal_plan,
)
from backend.app.core.china_equity_identifiers import normalize_listing_code  # noqa: E402
from backend.app.core.china_equity_bounded_plan import bounded_payload_count, iter_plan_coverage, iter_plan_rows, resolve_payload_manifest  # noqa: E402
from backend.app.core.storage_profile import (  # noqa: E402
    resolve_identity_state_backup_root,
    resolve_identity_state_path,
    resolve_unpublished_snapshot_path,
)
from backend.app.core.document_asset_store import DocumentAssetStore  # noqa: E402
from backend.app.core.subject_identity import InstallationIdentityState


TASK = "fr_a_share_database_foundation_canonical_consolidation_and_closed_loop_completion"
DEFAULT_EVIDENCE = ROOT / "runtime" / TASK / "closed_loop"
DEFAULT_PACKAGE = ROOT / "runtime" / TASK / "closed_loop_work_package_v1.json"


def _schema_file(root: Path, pattern: str) -> Path:
    matches = sorted(root.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"no schema source for {pattern}")
    return matches[0]


def _write_with_schema(rows: list[dict[str, Any]], schema_source: Path, target: Path) -> None:
    schema = pq.ParquetFile(schema_source).schema_arrow
    target.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows, schema=schema)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    pq.write_table(table, temporary, compression="zstd", version="2.6")
    os.replace(temporary, target)


def _sqlite_backup(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(source)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()


def _duckdb_bucket(value: str, modulus: int) -> int:
    """Return the accepted DuckDB hash bucket without per-row connection cost."""
    global _BUCKET_CONNECTION
    with _BUCKET_CONNECTION_LOCK:
        if _BUCKET_CONNECTION is None:
            _BUCKET_CONNECTION = duckdb.connect(":memory:")
        return int(_BUCKET_CONNECTION.execute("SELECT CAST(abs(hash(?)) % ? AS BIGINT)", [value, modulus]).fetchone()[0])


def _duckdb_bucket_map(values: list[str], modulus: int) -> dict[str, int]:
    """Compute a batch of accepted DuckDB buckets in one vector query."""
    unique = list(dict.fromkeys(str(value) for value in values))
    if not unique:
        return {}
    global _BUCKET_CONNECTION
    with _BUCKET_CONNECTION_LOCK:
        if _BUCKET_CONNECTION is None:
            _BUCKET_CONNECTION = duckdb.connect(":memory:")
        rows = _BUCKET_CONNECTION.execute(
            "SELECT value, CAST(abs(hash(value)) % ? AS BIGINT) FROM unnest(?) AS t(value)",
            [modulus, unique],
        ).fetchall()
    return {str(value): int(bucket) for value, bucket in rows}


def equity_lookup_buckets(values: list[str]) -> dict[str, int]:
    """The accepted bucket contract shared by initial and continuing Equity rows."""
    return _duckdb_bucket_map(values, 128)


def _series_for_instrument(control_path: Path, instrument_id: str) -> dict[str, str]:
    result: dict[str, str] = {}
    with closing(sqlite3.connect(control_path)) as connection:
        for series_id, attributes_json in connection.execute(
            """
            SELECT s.subject_id, s.attributes_json
            FROM subject_registry s
            JOIN subject_relationship_registry r
              ON r.from_type='series' AND r.from_id=s.subject_id
             AND r.to_type='instrument' AND r.to_id=? AND r.relationship_type='series_of'
            """,
            (instrument_id,),
        ):
            family = json.loads(attributes_json).get("series_family")
            if family:
                result[str(family)] = str(series_id)
    return result


def _series_for_all_instruments(control_path: Path) -> dict[str, dict[str, str]]:
    """Load the bounded series-to-instrument mapping in one control-db pass.

    The continuing Equity materializer touches millions of daily rows.  Querying
    ``subject_relationship_registry`` once per instrument would rescan the
    control database for every new instrument and dominate the materialization
    cost.  The relationship table is bounded metadata, so one streaming read is
    both simpler and materially more predictable than repeated point scans.
    """
    result: dict[str, dict[str, str]] = {}
    with closing(sqlite3.connect(control_path)) as connection:
        rows = connection.execute(
            """
            SELECT r.to_id, s.subject_id, s.attributes_json
            FROM subject_relationship_registry r
            JOIN subject_registry s ON s.subject_id=r.from_id
            WHERE r.from_type='series' AND r.to_type='instrument'
              AND r.relationship_type='series_of'
            """
        )
        for instrument_id, series_id, attributes_json in rows:
            family = json.loads(attributes_json).get("series_family")
            if family:
                result.setdefault(str(instrument_id), {})[str(family)] = str(series_id)
    return result


def _daily_fact_and_source(
    raw: dict[str, Any], binding: Any, series_id: str, fact_target: str, source_target: str,
    *, fact_bucket: int | None = None, source_bucket: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    metric_id = str(raw["metric_id"])
    economic_time = str(raw["economic_time"])
    logical_payload = {
        "economic_time": {"role": "observation_date", "value": economic_time},
        "fact_dimensions": {},
        "metric_id": metric_id,
        "subject": {"series_id": series_id, "subject_id": series_id, "subject_type": "series"},
        "version_effective_scope": {},
    }
    logical_key = stable_key("logical_fact", logical_payload)
    source_record = {
        "canonical_listing_id": binding.listing_id,
        "canonical_instrument_id": binding.instrument_id,
        "authoritative_episode_evidence_key": binding.episode_evidence_key,
        "source_alias_code": raw["code"],
        "adjustment_basis": raw["adjustment_basis"],
    }
    fact = {
        "logical_fact_key": logical_key,
        "logical_fact_base_key": logical_key.replace("logical_fact:", "logical_fact_base:", 1),
        "record_hash": hashlib_sha(f"{canonical_json(logical_payload)}|{raw['source_observation_key']}|{raw['normalized_value']}"),
        "dataset_name": "a_share_foundation_continuing_update_v1",
        "dataset_id": "a_share_foundation_continuing_update_v1",
        "source_family": raw["source_provider"],
        "metric_id": metric_id,
        "subject_type": "series",
        "subject_id": series_id,
        "series_id": series_id,
        "economic_time": economic_time,
        "primary_time_role": "observation_date",
        "fact_dimensions_json": "{}",
        "series_dimensions_json": canonical_json({"adjustment_basis": raw["adjustment_basis"]}),
        "version_effective_scope_json": "{}",
        "normalized_value": str(raw["normalized_value"]),
        "canonical_unit": raw["canonical_unit"],
        "canonical_currency": raw["canonical_currency"],
        "canonical_scale": "1",
        "normalization_evidence_json": canonical_json({
            "policy": "governed_public_daily_contract",
            "input_priority": 70,
            "source_normalization": dict(raw.get("normalization_evidence") or {}),
        }),
        "source_trace_json": canonical_json({"source_provider": raw["source_provider"], "source_interface": raw["source_interface"], "response_hash": raw["source_response_hash"]}),
        "direct_rank": 0,
        "classification": "unique_one_source_fact",
        "year": int(economic_time[:4]),
        "source_observation_key": raw["source_observation_key"],
        "source_domain": "equity",
        "source_partition_year": int(economic_time[:4]),
        "domain": "equity",
        "partition_year": int(economic_time[:4]),
        "fact_partition_locator": fact_target,
        "source_subject_hash_bucket": _duckdb_bucket(series_id, 128) if fact_bucket is None else fact_bucket,
    }
    source = {
        "source_observation_key": raw["source_observation_key"],
        "source_observation_base_key": stable_key("source_observation_base", {"source_observation_key": raw["source_observation_key"]}),
        "metric_id": metric_id,
        "record_hash": hashlib_sha(canonical_json({"source": raw["source_observation_key"], "raw_value": str(raw["raw_value"])})),
        "domain": "equity",
        "dataset_name": "a_share_foundation_continuing_update_v1",
        "entity_key": binding.instrument_id,
        "subject_candidate": binding.instrument_id,
        "event_date_or_period": economic_time,
        "partition_year": int(economic_time[:4]),
        "source_provider": raw["source_provider"],
        "source_interface": raw["source_interface"],
        "source_symbol": raw.get("source_symbol"),
        "source_field_locator": raw["raw_field"],
        "raw_value_json": canonical_json(str(raw["raw_value"])),
        "raw_unit": raw["raw_unit"],
        "raw_currency": raw["raw_currency"],
        "raw_scale": str(raw["raw_scale"]),
        "source_trace_json": canonical_json({"actual_upstream": raw["source_provider"], "response_hash": raw["source_response_hash"], "exchange": raw["exchange"], "code": raw["code"]}),
        "source_record_json": canonical_json(source_record),
        "first_seen_at_utc": raw.get("first_seen_at_utc") or utc_now(),
        "source_detail_semantic_state": "accepted_source_observation",
        "source_partition_locator": source_target,
        "key_bucket": _duckdb_bucket(raw["source_observation_key"], 128) if source_bucket is None else source_bucket,
    }
    return fact, source


def _daily_source_detail(
    raw: dict[str, Any], binding: Any, source_target: str, *, source_bucket: int | None = None,
) -> dict[str, Any]:
    economic_time = str(raw["economic_time"])
    source_key = str(raw["source_detail_key"])
    return {
        "source_observation_key": source_key,
        "source_observation_base_key": stable_key("source_observation_base", {"source_detail_key": source_key}),
        "metric_id": str(raw.get("metric_id") or "market.trade_amount"),
        "record_hash": hashlib_sha(canonical_json({"source": source_key, "raw_value": str(raw["raw_value"])})),
        "domain": "equity",
        "dataset_name": "a_share_foundation_continuing_update_v1",
        "entity_key": binding.instrument_id,
        "subject_candidate": binding.instrument_id,
        "event_date_or_period": economic_time,
        "partition_year": int(economic_time[:4]),
        "source_provider": raw["source_provider"],
        "source_interface": raw["source_interface"],
        "source_symbol": raw.get("source_symbol"),
        "source_field_locator": raw["source_field"],
        "raw_value_json": canonical_json(str(raw["raw_value"])),
        "raw_unit": raw["raw_unit"],
        "raw_currency": raw["raw_currency"],
        "raw_scale": raw.get("raw_scale"),
        "source_trace_json": canonical_json({
            "actual_upstream": raw["source_provider"],
            "response_hash": raw["source_response_hash"],
            "exchange": raw["exchange"], "code": raw["code"],
            "promotion_status": "source_detail_only",
        }),
        "source_record_json": canonical_json({
            "canonical_listing_id": binding.listing_id,
            "canonical_instrument_id": binding.instrument_id,
            "authoritative_episode_evidence_key": binding.episode_evidence_key,
            "source_alias_code": raw["code"],
            "adjustment_basis": raw["adjustment_basis"],
        }),
        "first_seen_at_utc": raw.get("first_seen_at_utc") or utc_now(),
        "source_detail_semantic_state": raw["source_detail_semantic_state"],
        "source_partition_locator": source_target,
        "key_bucket": _duckdb_bucket(source_key, 128) if source_bucket is None else source_bucket,
    }


def _existing_series_by_object_key(state: InstallationIdentityState) -> dict[str, dict[str, Any]]:
    result = {}
    for row in state.rows():
        if row["subject_type"] != "series":
            continue
        key = row.get("decision_attributes", {}).get("a_share_financial_series_object_key")
        if key:
            result[str(key)] = row
    return result


def _ensure_financial_series(
    state: InstallationIdentityState,
    required: list[tuple[str, str, str]],
) -> tuple[dict[tuple[str, str, str], str], int]:
    if not required:
        return {}, 0
    existing = _existing_series_by_object_key(state)
    missing = []
    keys = {}
    for entity_id, metric_id, accounting_scope in sorted(set(required)):
        object_key = financial_series_object_key(entity_id, metric_id, accounting_scope)
        keys[(entity_id, metric_id, accounting_scope)] = object_key
        if object_key not in existing:
            missing.append(
                {
                    "subject_type": "series",
                    "accepted_identity_statement": (
                        f"Accepted A-share {accounting_scope} {metric_id} reporting series for {entity_id}"
                    ),
                    "economic_object_type": "entity_financial_metric_series",
                    "decision_attributes": {
                        "a_share_financial_series_object_key": object_key,
                        "universe": "a_share",
                        "metric_id": metric_id,
                        "accounting_scope": accounting_scope,
                        "parent_entity_id": entity_id,
                    },
                    "provenance_refs": ["accepted A-share financial/KPI source observation"],
                }
            )
    if missing:
        state.create_decisions_batch(missing)
        existing = _existing_series_by_object_key(state)
    return (
        {
            triple: existing[object_key]["subject_id"]
            for triple, object_key in keys.items()
        },
        len(missing),
    )


def _fact_row(raw: dict[str, Any], binding: Any, series_id: str, target: str) -> dict[str, Any]:
    metric_id = canonical_financial_metric(str(raw["metric_id"]))
    period = str(raw["period_end"])
    version_scope = dict(raw.get("version_effective_scope") or {})
    logical_key = financial_logical_fact_key(binding.entity_id, metric_id, period, version_scope)
    logical_base_key = financial_logical_fact_key(binding.entity_id, metric_id, period)
    unit = str(raw["canonical_unit"])
    currency = str(raw.get("canonical_currency") or "not_applicable")
    value = str(raw["normalized_value"])
    trace = {
        "source_provider": raw["source_provider"],
        "source_interface": raw["source_interface"],
        "source_symbol": raw.get("source_symbol"),
        "source_document_or_response_hash": raw.get("source_response_hash"),
        "authoritative_subject_binding": binding.episode_evidence_key,
        "closed_loop_replay": bool(raw.get("closed_loop_replay")),
    }
    record_material = {
        "logical_fact_key": logical_key,
        "source_observation_key": raw["source_observation_key"],
        "normalized_value": value,
        "series_id": series_id,
    }
    return {
        "logical_fact_key": logical_key,
        "logical_fact_base_key": logical_base_key.replace("logical_fact:", "logical_fact_base:", 1),
        "record_hash": stable_key("record", record_material).split(":", 1)[1],
        "dataset_name": "a_share_foundation_incremental_update_v1",
        "dataset_id": "a_share_foundation_incremental_update_v1",
        "source_family": "structured_public_source",
        "metric_id": metric_id,
        "subject_type": "entity",
        "subject_id": binding.entity_id,
        "series_id": series_id,
        "economic_time": period,
        "primary_time_role": "period_end",
        "fact_dimensions_json": "{}",
        "series_dimensions_json": canonical_json({"accounting_scope": raw.get("accounting_scope", "consolidated")}),
        "version_effective_scope_json": canonical_json(version_scope),
        "normalized_value": value,
        "canonical_unit": unit,
        "canonical_currency": currency,
        "canonical_scale": "1",
        "normalization_evidence_json": canonical_json({"source_contract": raw.get("normalization_evidence", "accepted_source_native_scale"), "canonical_scale": 1}),
        "source_trace_json": canonical_json(trace),
        "direct_rank": int(raw.get("direct_rank", 0)),
        "classification": "canonical_accepted_financial_fact",
        "year": int(period[:4]),
        "source_observation_key": raw["source_observation_key"],
        "source_domain": "financial_statements",
        "source_partition_year": int(period[:4]),
        "source_subject_hash_bucket": int(hashlib_sha(binding.entity_id)[:8], 16) % 32,
        "domain": "financial_statements",
        "partition_year": int(period[:4]),
        "fact_partition_locator": target,
    }


def hashlib_sha(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _source_row(raw: dict[str, Any], binding: Any, metric_id: str, target: str) -> dict[str, Any]:
    period = str(raw["period_end"])
    source_record = dict(raw)
    source_record["canonical_subject_crosswalk"] = binding.entity_id
    payload_hash = hashlib_sha(canonical_json(source_record))
    return {
        "source_observation_key": raw["source_observation_key"],
        "source_observation_base_key": stable_key("source_observation_base", {"source_observation_key": raw["source_observation_key"]}),
        "metric_id": metric_id,
        "record_hash": payload_hash,
        "domain": "financial_statements",
        "dataset_name": "a_share_foundation_incremental_update_v1",
        "entity_key": raw.get("source_symbol") or raw.get("code"),
        "subject_candidate": f"{raw['exchange']}:{str(raw['code']).zfill(6)}",
        "event_date_or_period": period,
        "partition_year": int(period[:4]),
        "source_provider": raw["source_provider"],
        "source_interface": raw["source_interface"],
        "source_symbol": raw.get("source_symbol"),
        "source_field_locator": raw.get("source_field_locator"),
        "raw_value_json": canonical_json(raw.get("raw_value", raw["normalized_value"])),
        "raw_unit": raw.get("raw_unit", raw["canonical_unit"]),
        "raw_currency": raw.get("raw_currency", raw.get("canonical_currency")),
        "raw_scale": str(raw.get("raw_scale", 1)),
        "source_trace_json": canonical_json({"response_hash": raw.get("source_response_hash"), "route": raw["source_interface"]}),
        "source_record_json": canonical_json(source_record),
        "first_seen_at_utc": raw.get("first_seen_at_utc") or "2026-08-15T20:18:30Z",
        "source_detail_semantic_state": "canonical_source_observation",
        "key_bucket": int(hashlib_sha(raw["source_observation_key"])[:8], 16) % 128,
        "source_partition_locator": target,
    }


def _materialize_document_rows(
    items: list[dict[str, Any]],
    index: AcceptedChinaEquityEpisodeIndex,
    plan: dict[str, Any],
    resolution_lookup: Mapping[tuple[str, str], tuple[dict[str, Any], ...]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    store = DocumentAssetStore()
    rows: list[dict[str, Any]] = []
    reused = 0
    written_bytes = 0
    for item in items:
        binding = _resolve_plan_binding(
            index,
            plan,
            item["exchange"],
            item["code"],
            item.get("identity_effective_at") or item.get("effective_at"),
            resolution_lookup,
        )
        source_path = Path(item["asset_source_path"])
        if sha256_file(source_path) != item["asset_sha256"]:
            raise ValueError(f"document source hash changed before canonical asset write: {source_path}")
        provenance = {
            "source_provider": "CNINFO",
            "announcement_id": item["announcement_id"],
            "source_url": item["source_url"],
            "published_date": item.get("effective_at"),
            "source_observation_key": item["source_observation_key"],
            "entity_id": binding.entity_id,
            "instrument_id": binding.instrument_id,
            "listing_id": binding.listing_id,
            "episode_evidence_key": binding.episode_evidence_key,
        }
        stored = store.store(source_path, mime_type=item.get("mime_type", "application/pdf"), provenance=provenance)
        reused += int(stored.reused_existing_asset)
        written_bytes += 0 if stored.reused_existing_asset else stored.byte_count
        row = {key: value for key, value in item.items() if key != "asset_source_path"}
        row.update({
            "entity_id": binding.entity_id,
            "instrument_id": binding.instrument_id,
            "listing_id": binding.listing_id,
            "episode_evidence_key": binding.episode_evidence_key,
            **stored.as_dict(),
        })
        rows.append(row)
    return rows, {
        "document_asset_count": len(rows),
        "document_asset_reused_count": reused,
        "document_asset_written_bytes": written_bytes,
    }


def _lineage_row(fact: dict[str, Any], source: dict[str, Any], target: str) -> dict[str, Any]:
    return {
        "old_lineage_rowid": None,
        "legacy_source_observation_key": source["source_observation_key"],
        "legacy_logical_fact_key": fact["logical_fact_key"],
        "corrected_source_observation_key": source["source_observation_key"],
        "corrected_metric_id": fact["metric_id"],
        "lineage_normalized_value": fact["normalized_value"],
        "lineage_canonical_unit": fact["canonical_unit"],
        "lineage_canonical_currency": fact["canonical_currency"],
        "direct_rank": fact["direct_rank"],
        "version_effective_scope_json": fact["version_effective_scope_json"],
        "source_partition_locator": source["source_partition_locator"],
        "fact_partition_locator": fact["fact_partition_locator"],
        "lineage_classification": "accepted_fact_lineage",
        "bucket_group": "closed_loop",
        "corrected_logical_fact_key": fact["logical_fact_key"],
    }


def _manifest_row(path: Path, root: Path) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    parquet = pq.ParquetFile(path)
    return {
        "partition_id": hashlib_sha(canonical_json({"layer_name": relative.split("/", 1)[0], "relative_path": relative})),
        "layer_name": relative.split("/", 1)[0],
        "relative_path": relative,
        "row_count": parquet.metadata.num_rows,
        "byte_count": path.stat().st_size,
        "schema_sha256": hashlib_sha(str(parquet.schema_arrow)),
        "content_sha256": sha256_file(path),
        "completed": True,
        "created_at_utc": utc_now(),
    }


def _resolve_plan_binding(
    index: AcceptedChinaEquityEpisodeIndex,
    plan: dict[str, Any],
    exchange: str,
    code: str,
    effective_at: str | None,
    resolution_lookup: Mapping[tuple[str, str], tuple[dict[str, Any], ...]] | None = None,
) -> ChinaEquitySubjectBinding:
    normalized_exchange = str(exchange).upper()
    normalized_code = normalize_listing_code(normalized_exchange, code)
    if resolution_lookup is None:
        resolutions = list(plan.get("identity_resolutions") or ())
        if plan.get("identity_resolution"):
            resolutions.append(plan["identity_resolution"])
    else:
        resolutions = list(resolution_lookup.get((normalized_exchange, normalized_code), ()))
    for resolution in resolutions:
        if normalized_exchange != str(resolution["exchange"]).upper() or normalized_code != normalize_listing_code(resolution["exchange"], resolution["code"]):
            continue
        start = resolution.get("listing_start_date")
        end = resolution.get("listing_end_date")
        if effective_at is None or ((not start or effective_at >= start) and (not end or effective_at <= end)):
            binding = ChinaEquitySubjectBinding(
                exchange=normalized_exchange,
                code=normalized_code,
                entity_id=resolution["entity_id"],
                instrument_id=resolution["instrument_id"],
                listing_id=resolution["listing_id"],
                episode_evidence_key=resolution["episode_evidence_key"],
                lifecycle_status=resolution["lifecycle_status"],
                listing_start_date=start,
                listing_end_date=end,
                code_aliases=((normalized_code, start, end),),
            )
            try:
                accepted = index.resolve(normalized_exchange, normalized_code, effective_at)
            except KeyError:
                accepted = None
            if accepted is not None and (
                accepted.entity_id,
                accepted.instrument_id,
                accepted.listing_id,
                accepted.episode_evidence_key,
            ) != (
                binding.entity_id,
                binding.instrument_id,
                binding.listing_id,
                binding.episode_evidence_key,
            ):
                raise ValueError("discovered identity resolution conflicts with accepted authoritative owner")
            return binding
    return index.resolve(normalized_exchange, normalized_code, effective_at)


def _apply_discovered_identity(connection: sqlite3.Connection, resolution: dict[str, Any], now: str) -> None:
    exchange = str(resolution["exchange"]).upper()
    code = normalize_listing_code(exchange, resolution["code"])
    start = resolution.get("listing_start_date")
    end = resolution.get("listing_end_date")
    share_type = str(resolution.get("share_type") or ("HKEX_EQUITY" if exchange == "HKEX" else "A_share"))
    market_jurisdiction = str(resolution.get("market_jurisdiction") or ("HK" if exchange == "HKEX" else "CN"))
    security_classification = str(
        resolution.get("security_classification")
        or ("hong_kong_equity" if exchange == "HKEX" else "a_share")
    )
    physical_market = market_jurisdiction if exchange == "HKEX" else "CN_A_SHARE"
    instrument_venue = exchange if exchange == "HKEX" else None
    alias = [{"code": code, "effective_from": start, "effective_to": end, "exchange": exchange, "role": "exchange_code", "scope": f"{exchange}:{share_type}"}]
    subjects = [
        (
            "entity", resolution["entity_id"], "equities", None, physical_market, None, None, None, "[]",
            canonical_json({"authoritative_entity_decision_key": resolution["entity_object_key"], "identity_contract": "installation_local_standard_id_ready", "universe": "Equity", "region": "CN", "market_jurisdiction": market_jurisdiction, "share_type": share_type}),
            "standard_id_ready", now,
        ),
        (
            "instrument", resolution["instrument_id"], "equities", None, physical_market, instrument_venue, start, end, canonical_json(alias),
            canonical_json({"authoritative_instrument_decision_key": resolution["instrument_object_key"], "identity_contract": "installation_local_standard_id_ready", "instrument_class": "equity_security", "economic_object_type": resolution.get("instrument_economic_object_type", "equity_security"), "universe": "Equity", "region": "CN", "market_jurisdiction": market_jurisdiction, "venue": exchange, "share_type": share_type, "security_classification": security_classification, "reference_classification": resolution.get("reference_classification"), "trading_currency": resolution.get("trading_currency")}),
            "standard_id_ready", now,
        ),
        (
            "listing", resolution["listing_id"], "equities", None, physical_market, exchange, start, end, canonical_json(alias),
            canonical_json({"episode_evidence_key": resolution["episode_evidence_key"], "exchange": exchange, "identity_contract": "installation_local_standard_id_ready", "universe": "Equity", "region": "CN", "market_jurisdiction": market_jurisdiction, "venue": exchange, "lifecycle_status": resolution["lifecycle_status"], "listing_start_boundary": resolution.get("listing_start_boundary", "exact"), "security_name": resolution.get("security_name"), "share_type": share_type, "security_classification": security_classification, "reference_classification": resolution.get("reference_classification"), "trading_currency": resolution.get("trading_currency"), "board": resolution.get("board")}),
            "standard_id_ready", now,
        ),
    ]
    for family, series_id in sorted(resolution["series"].items()):
        subjects.append((
            "series", series_id, "equities", None, physical_market, exchange, start, end, "[]",
            canonical_json({"identity_contract": "installation_local_standard_id_ready", "universe": "Equity", "region": "CN", "market_jurisdiction": market_jurisdiction, "venue": exchange, "series_family": family, "series_dimensions": {"adjustment_basis": "unadjusted"}}),
            "standard_id_ready", now,
        ))
    existing_subject_keys = {(row[0], row[1]) for row in subjects
        if connection.execute("SELECT 1 FROM subject_registry WHERE subject_type=? AND subject_id=?", (row[0], row[1])).fetchone()}
    connection.executemany("INSERT OR IGNORE INTO subject_registry VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", subjects)
    # Existing subjects retain their durable IDs.  A later authoritative name
    # observation updates only external/alias state and never allocates a new
    # economic object.
    if resolution.get("name_effective_at") and resolution.get("security_name"):
        for subject_type, subject_id in (
            ("instrument", resolution["instrument_id"]),
            ("listing", resolution["listing_id"]),
        ):
            found = connection.execute(
                "SELECT attributes_json FROM subject_registry WHERE subject_type=? AND subject_id=?",
                (subject_type, subject_id),
            ).fetchone()
            if not found:
                continue
            attributes = json.loads(found[0])
            aliases = list(attributes.get("name_aliases") or [])
            candidate = {
                "alias_kind": "security_short_name",
                "date_role": "authoritative_record_observation",
                "effective_from": resolution["name_effective_at"],
                "effective_to": resolution["name_effective_at"],
                "source_id": "bse_current_pages",
                "value": resolution["security_name"],
            }
            if candidate not in aliases:
                aliases.append(candidate)
            attributes["name_aliases"] = aliases
            attributes["security_name"] = resolution["security_name"]
            connection.execute(
                "UPDATE subject_registry SET attributes_json=?,updated_at_utc=? WHERE subject_type=? AND subject_id=?",
                (canonical_json(attributes), now, subject_type, subject_id),
            )
    identity_basis = (
        "accepted Hong Kong Equity market-specific identity owner"
        if exchange == "HKEX" else "authoritative issuer subject crosswalk"
    )
    relationships = [
        ("instrument", resolution["instrument_id"], "entity", resolution["entity_id"], "issued_by", None, None, {"basis": identity_basis}),
        ("listing", resolution["listing_id"], "instrument", resolution["instrument_id"], "listed_as", start, end, {"code_aliases": alias, "exchange": exchange}),
    ]
    for family, series_id in sorted(resolution["series"].items()):
        relationships.extend([
            ("series", series_id, "instrument", resolution["instrument_id"], "series_of", start, end, {"series_family": family}),
            ("series", series_id, "listing", resolution["listing_id"], "quoted_on", start, end, {"series_family": family}),
        ])
    for from_type, from_id, to_type, to_id, relationship_type, effective_start, effective_end, attributes in relationships:
        rid = relationship_id(from_type, from_id, to_type, to_id, relationship_type, effective_start, effective_end)
        existing = connection.execute("SELECT 1 FROM subject_relationship_registry WHERE relationship_id=?", (rid,)).fetchone()
        if existing is None and (from_type, from_id) in existing_subject_keys:
            existing = connection.execute(
            """
            SELECT 1 FROM subject_relationship_registry
            WHERE from_type=? AND from_id=? AND to_type=? AND to_id=? AND relationship_type=?
              AND effective_start IS ? AND effective_end IS ?
            LIMIT 1
            """,
            (from_type, from_id, to_type, to_id, relationship_type, effective_start, effective_end),
            ).fetchone()
        if existing:
            continue
        connection.execute(
            "INSERT OR IGNORE INTO subject_relationship_registry VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                rid,
                from_type, from_id, to_type, to_id, relationship_type, effective_start, effective_end,
                canonical_json(attributes), "standard_id_ready", now,
            ),
        )


def _control_apply(
    control_path: Path,
    series: dict[tuple[str, str, str], str],
    coverage: list[dict[str, Any]],
    identity_resolutions: list[dict[str, Any]] | None = None,
    lifecycle_events: list[dict[str, Any]] | None = None,
) -> None:
    now = utc_now()
    with closing(sqlite3.connect(control_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        for resolution in identity_resolutions or ():
            _apply_discovered_identity(connection, resolution, now)
        apply_equity_lifecycle_events(connection, lifecycle_events or [])
        for (entity_id, metric_id, scope), series_id in series.items():
            attrs = canonical_json({"accounting_scope": scope, "identity_contract": "installation_local_standard_id_ready", "metric_id": metric_id, "series_family": "financial_reporting"})
            connection.execute(
                "INSERT OR IGNORE INTO subject_registry VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("series", series_id, "financial_statements", series_id, "CN_A_SHARE", None, None, None, "[]", attrs, "standard_id_ready", now),
            )
            rid = relationship_id("series", series_id, "entity", entity_id, "series_of")
            connection.execute(
                "INSERT OR IGNORE INTO subject_relationship_registry VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (rid, "series", series_id, "entity", entity_id, "series_of", None, None, canonical_json({"identity_evidence": "accepted entity financial metric series"}), "standard_id_ready", now),
            )
        for row in coverage:
            connection.execute(
                "DELETE FROM coverage_summary WHERE universe IN ('a_share','CN_A_SHARE') AND subject_id=? AND metric_id=?",
                (row["entity_id"], row["metric_id"]),
            )
            connection.execute(
                "INSERT OR REPLACE INTO coverage_summary VALUES (?,?,?,?,?,?,?)",
                ("a_share", row["entity_id"], row["metric_id"], row["coverage_state"], row["fact_count"], row.get("min_time"), row.get("max_time")),
            )
        connection.commit()


def apply_equity_lifecycle_events(connection: sqlite3.Connection, events: list[dict[str, Any]]) -> None:
    """Amend current snapshot metadata, preserving subjects and relationship IDs.

    A dated listing end is not an issuer/instrument identity merger. Prior
    sealed graphs are untouched; the existing edge records acquire their
    authoritative effective end in the unpublished successor only.
    """
    for event in sorted(events, key=lambda r: (r["effective_date"], r["event_type"])):
        listing_id = event["listing_id"]
        row = connection.execute("SELECT attributes_json,code_aliases_json FROM subject_registry WHERE subject_type='listing' AND subject_id=?", (listing_id,)).fetchone()
        if row is None:
            raise ValueError("lifecycle event has no accepted listing subject")
        attrs = json.loads(row[0]); aliases = json.loads(row[1])
        if event.get("date_role") == "actual_market_status_effective":
            attrs["market_status_at_cutoff"] = "trading" if event["event_type"] == "trading_resumption" else "suspended"
            attrs["market_status_effective_date"] = event["effective_date"]
            connection.execute("UPDATE subject_registry SET attributes_json=? WHERE subject_type='listing' AND subject_id=?", (canonical_json(attrs), listing_id))
        if event["event_type"] != "listing_termination" or event.get("date_role") != "actual_listing_end":
            continue
        end = event["effective_date"]
        attrs["lifecycle_status"] = "ended"
        for alias in aliases:
            alias["effective_to"] = min(alias.get("effective_to") or end, end)
        series_ids = [r[0] for r in connection.execute("SELECT from_id FROM subject_relationship_registry WHERE relationship_type='quoted_on' AND to_type='listing' AND to_id=?", (listing_id,))]
        connection.execute("UPDATE subject_registry SET effective_end=?,attributes_json=?,code_aliases_json=? WHERE subject_type='listing' AND subject_id=?", (end, canonical_json(attrs), canonical_json(aliases), listing_id))
        for sid in series_ids:
            connection.execute("UPDATE subject_registry SET effective_end=? WHERE subject_type='series' AND subject_id=?", (end, sid))
        keys = [listing_id, *series_ids]
        edges = connection.execute("SELECT relationship_id,relationship_type FROM subject_relationship_registry WHERE from_id IN (" + ",".join("?" for _ in keys) + ")", keys).fetchall()
        for rid, kind in edges:
            if kind in {"listed_as", "series_of", "quoted_on"}:
                connection.execute("UPDATE subject_relationship_registry SET effective_end=? WHERE relationship_id=?", (end, rid))


def complete_accepted_daily_series_dimensions(control_path: Path, identity_owner: Path) -> list[str]:
    """Repair the old ingress omission on accepted canonical daily Series only.

    This is the same unadjusted contract used by _apply_discovered_identity and
    _daily_fact_and_source, not a derivation from price observations or the list
    of query capabilities. It neither allocates UUIDs nor converts values.
    A conflicting explicit basis, family or parent remains an error.
    """
    repaired = []
    objects = json.loads(identity_owner.read_text(encoding="utf-8"))["objects"]
    with closing(sqlite3.connect(control_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        for obj in objects:
            for series in obj.get("series", []):
                if series["series_family"] not in {"daily_ohlc", "market_volume", "market_trade_amount", "market_turnover_rate"}:
                    continue
                row = connection.execute(
                    "SELECT attributes_json,resolution_status FROM subject_registry WHERE subject_type='series' AND subject_id=?",
                    (series["series_id"],),
                ).fetchone()
                if row is None or row[1] != "standard_id_ready":
                    raise ValueError("accepted canonical daily Series is missing or not promoted")
                attrs = json.loads(row[0])
                dimensions = dict(attrs.get("series_dimensions") or {})
                if dimensions.get("adjustment_basis"):
                    if dimensions["adjustment_basis"] != "unadjusted":
                        raise ValueError("accepted daily Series conflicts with the unadjusted ingress contract")
                    continue
                parent = connection.execute(
                    "SELECT attributes_json FROM subject_relationship_registry WHERE from_type='series' AND from_id=? "
                    "AND to_type='listing' AND to_id=? AND relationship_type='quoted_on' AND resolution_status='standard_id_ready'",
                    (series["series_id"], obj["listing_id"]),
                ).fetchone()
                if parent is None or json.loads(parent[0]).get("series_family") != series["series_family"]:
                    raise ValueError("accepted daily Series has no proved family/listing relationship")
                dimensions["adjustment_basis"] = "unadjusted"
                attrs["series_dimensions"] = dimensions
                connection.execute("UPDATE subject_registry SET attributes_json=? WHERE subject_type='series' AND subject_id=?",
                                   (canonical_json(attrs), series["series_id"]))
                repaired.append(series["series_id"])
        connection.commit()
    return repaired


def run_work_package(
    package_path: Path,
    output_root: Path,
    *,
    inject_failure_after: str | None = None,
) -> dict[str, Any]:
    package = json.loads(package_path.read_text(encoding="utf-8"))
    output_root.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_root / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.is_file() else {"completed": []}
    completed = set(checkpoint.get("completed", []))
    index = AcceptedChinaEquityEpisodeIndex.load(Path(package["lifecycle_owner_path"]), Path(package["identity_reconciliation_path"]))
    refresh_results = []
    for item in package.get("authoritative_refresh", []):
        binding = index.resolve(item["exchange"], item["code"])
        refresh_results.append({"episode_evidence_key": binding.episode_evidence_key, "result": "matched_accepted_authoritative_subject"})

    observations = []
    duplicate_inputs = 0
    seen = {}
    required = []
    for raw in package.get("financial_observations", []):
        binding = index.resolve(raw["exchange"], raw["code"])
        raw = dict(raw)
        raw["metric_id"] = canonical_financial_metric(raw["metric_id"])
        raw["accounting_scope"] = raw.get("accounting_scope", "consolidated")
        logical_key = financial_logical_fact_key(
            binding.entity_id,
            raw["metric_id"],
            raw["period_end"],
            raw.get("version_effective_scope"),
        )
        signature = (str(raw["normalized_value"]), raw["source_observation_key"])
        if logical_key in seen:
            if seen[logical_key] != signature:
                raise ValueError(f"conflicting duplicate update input: {logical_key}")
            duplicate_inputs += 1
            continue
        seen[logical_key] = signature
        observations.append((raw, binding))
        required.append((binding.entity_id, raw["metric_id"], raw["accounting_scope"]))

    identity = InstallationIdentityState(resolve_identity_state_path(), resolve_identity_state_backup_root())
    before_assignments = len(identity.rows())
    series, created = _ensure_financial_series(identity, required)
    after_assignments = len(identity.rows())
    completed.add("identity_ready")
    write_json_atomic(checkpoint_path, {"completed": sorted(completed), "identity_assignments_after": after_assignments})
    if inject_failure_after == "identity_ready":
        raise RuntimeError("controlled_failure_after_identity_ready")

    predecessor_id = package["predecessor_snapshot_id"]
    successor_id = package["successor_snapshot_id"]
    clone = clone_snapshot_from_manifest(predecessor_id, successor_id)
    successor = resolve_unpublished_snapshot_path(successor_id)
    predecessor = resolve_unpublished_snapshot_path(predecessor_id)
    control_source = Path(package["predecessor_control_path"])
    control_target = Path(package["successor_control_path"])
    if not control_target.is_file():
        _sqlite_backup(control_source, control_target)

    fact_rows = []
    source_rows = []
    lineage_rows = []
    for raw, binding in observations:
        year = str(raw["period_end"])[:4]
        fact_relative = f"standard_facts/domain=financial_statements/year={year}/part-closed-loop-real-update.parquet"
        source_relative = f"source_observations/domain=financial_statements/year={year}/part-closed-loop-real-update.parquet"
        series_id = series[(binding.entity_id, raw["metric_id"], raw["accounting_scope"])]
        fact = _fact_row(raw, binding, series_id, fact_relative)
        source = _source_row(raw, binding, raw["metric_id"], source_relative)
        fact_rows.append(fact)
        source_rows.append(source)
        lineage_rows.append(_lineage_row(fact, source, "metadata/corrected_lineage/bucket_group=closed_loop/part-real-update.parquet"))

    if fact_rows:
        years = sorted({row["partition_year"] for row in fact_rows})
        for year in years:
            target = successor / f"standard_facts/domain=financial_statements/year={year}/part-closed-loop-real-update.parquet"
            schema = _schema_file(predecessor, "standard_facts/domain=financial_statements/year=*/*.parquet")
            _write_with_schema([row for row in fact_rows if row["partition_year"] == year], schema, target)
            target = successor / f"source_observations/domain=financial_statements/year={year}/part-closed-loop-real-update.parquet"
            source_table = pa.Table.from_pylist(
                [row for row in source_rows if row["partition_year"] == year]
            )
            pq.write_table(source_table, target, compression="zstd", version="2.6")
        lineage_target = successor / "metadata/corrected_lineage/bucket_group=closed_loop/part-real-update.parquet"
        lineage_schema = _schema_file(predecessor, "metadata/corrected_lineage/bucket_group=*/*.parquet")
        _write_with_schema(lineage_rows, lineage_schema, lineage_target)

    document_rows = []
    for item in package.get("documents", []):
        binding = index.resolve(item["exchange"], item["code"])
        document_rows.append({**item, "entity_id": binding.entity_id, "instrument_id": binding.instrument_id, "listing_id": binding.listing_id, "episode_evidence_key": binding.episode_evidence_key})
    document_target = successor / "metadata/document_lookup/part-closed-loop-real-update.parquet"
    if document_rows:
        document_target.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(document_rows), document_target, compression="zstd")

    coverage = []
    by_metric = Counter((row["subject_id"], row["metric_id"]) for row in fact_rows)
    for expected in package.get("coverage_expectations", []):
        binding = index.resolve(expected["exchange"], expected["code"])
        metric_id = canonical_financial_metric(expected["metric_id"])
        count = by_metric[(binding.entity_id, metric_id)]
        coverage.append({
            "entity_id": binding.entity_id,
            "metric_id": metric_id,
            "coverage_state": derive_coverage_state(
                applicable=bool(expected.get("applicable", True)),
                observed_fact_count=count,
                source_route_available=bool(expected.get("source_route_available", True)),
                source_contract_limited=bool(expected.get("source_contract_limited", False)),
            ),
            "fact_count": count,
            "min_time": expected.get("min_time"),
            "max_time": expected.get("max_time"),
        })
    _control_apply(control_target, series, coverage)

    predecessor_manifest = json.loads((predecessor / "metadata/corrected_candidate_manifest_v1.json").read_text(encoding="utf-8"))
    new_files = []
    for path in sorted(successor.rglob("*.parquet")):
        if "part-closed-loop-real-update" in path.name or "bucket_group=closed_loop" in path.as_posix():
            row = _manifest_row(path, successor)
            row["created_at_utc"] = package["created_at_utc"]
            new_files.append(row)
    files = [dict(row) for row in predecessor_manifest["files"]]
    by_path = {row["relative_path"]: row for row in files}
    for row in new_files:
        by_path[row["relative_path"]] = row
    files = sorted(by_path.values(), key=lambda row: row["relative_path"])
    manifest = dict(predecessor_manifest)
    manifest.update({
        "schema_version": "fr_a_share_foundation_closed_loop_successor_manifest_v1",
        "snapshot_id": successor_id,
        "predecessor_snapshot_id": predecessor_id,
        "publication_state": "unpublished_closed_loop_proof",
        "files": files,
        "file_count": len(files),
        "compressed_bytes": sum(int(row["byte_count"]) for row in files),
        "accepted_fact_output_count": int(predecessor_manifest["accepted_fact_output_count"]) + len(fact_rows),
        "source_observation_count": int(predecessor_manifest["source_observation_count"]) + len(source_rows),
        "created_at_utc": package["created_at_utc"],
    })
    manifest = reconcile_manifest_aggregate_counts(manifest)
    manifest_path = successor / "metadata/corrected_candidate_manifest_v1.json"
    write_json_atomic(manifest_path, manifest)
    completed.add("successor_materialized")
    write_json_atomic(checkpoint_path, {"completed": sorted(completed), "identity_assignments_after": after_assignments})

    result = {
        "schema_version": "fr_a_share_foundation_closed_loop_result_v1",
        "package_id": package["package_id"],
        "predecessor_snapshot_id": predecessor_id,
        "successor_snapshot_id": successor_id,
        "authoritative_refresh": refresh_results,
        "financial_input_rows": len(package.get("financial_observations", [])),
        "financial_fact_rows": len(fact_rows),
        "source_observation_rows": len(source_rows),
        "document_rows": len(document_rows),
        "duplicate_input_rows_deduplicated": duplicate_inputs,
        "identity_assignments_before": before_assignments,
        "identity_assignments_after": after_assignments,
        "identity_assignments_created": created,
        "coverage_counts": dict(sorted(Counter(row["coverage_state"] for row in coverage).items())),
        "clone": clone,
        "manifest_sha256": sha256_file(manifest_path),
        "active_pointer_modified": False,
        "legacy_sqlite_used": False,
        "archived_updater_used": False,
        "result": "PASS",
    }
    write_json_atomic(output_root / "closed_loop_result_v1.json", result)
    return result


def _canonical_financial_keys_exist(snapshot: Path, logical_keys: list[str]) -> tuple[set[str], int, int]:
    """Resolve a batch with one pass per touched bucket and no daily locator scan."""
    by_bucket: dict[int, set[str]] = {}
    for key in logical_keys:
        by_bucket.setdefault(_duckdb_bucket(key, 64), set()).add(key)
    found: set[str] = set()
    bytes_read = 0
    files_read = 0
    for bucket, requested in sorted(by_bucket.items()):
        root = snapshot / f"metadata/logical_key_locators/bucket_group={bucket:02d}"
        paths = []
        canonical = root / "part-a-share-financial-canonical.parquet"
        if canonical.is_file():
            paths.append(canonical)
        paths.extend(sorted(root.glob("part-continuing-update*.parquet")))
        for path in paths:
            files_read += 1
            bytes_read += path.stat().st_size
            values = set(
                pq.ParquetFile(path).read(columns=["logical_fact_key"]).column("logical_fact_key").to_pylist()
            )
            found.update(requested & values)
            if requested <= found:
                break
    return found, bytes_read, files_read


def _write_delta_indexes(
    predecessor: Path,
    successor: Path,
    fact_rows: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    delta_tag: str,
) -> list[Path]:
    source_by_key = {row["source_observation_key"]: row for row in source_rows}
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for fact in fact_rows:
        source = source_by_key[fact["source_observation_key"]]
        logical_bucket = _duckdb_bucket(fact["logical_fact_key"], 64)
        source_bucket = _duckdb_bucket(source["source_observation_key"], 64)
        common = {
            "old_lineage_rowid": None,
            "legacy_source_observation_key": source["source_observation_key"],
            "legacy_logical_fact_key": fact["logical_fact_key"],
            "corrected_source_observation_key": source["source_observation_key"],
            "corrected_metric_id": fact["metric_id"],
            "lineage_normalized_value": fact["normalized_value"],
            "lineage_canonical_unit": fact["canonical_unit"],
            "lineage_canonical_currency": fact["canonical_currency"],
            "direct_rank": fact["direct_rank"],
            "version_effective_scope_json": fact["version_effective_scope_json"],
            "source_partition_locator": source["source_partition_locator"],
            "fact_partition_locator": fact["fact_partition_locator"],
            "lineage_classification": "accepted_fact_lineage",
            "bucket_group": f"{source_bucket:02d}",
            "corrected_logical_fact_key": fact["logical_fact_key"],
        }
        grouped.setdefault(("corrected_lineage", source_bucket), []).append(common)
        grouped.setdefault(("logical_lineage_lookup", logical_bucket), []).append({**common, "logical_bucket_group": f"{logical_bucket:02d}"})
        grouped.setdefault(("logical_key_locators", logical_bucket), []).append({
            "logical_fact_key": fact["logical_fact_key"],
            "logical_fact_base_key": fact["logical_fact_base_key"],
            "legacy_logical_fact_key": fact["logical_fact_key"],
            "legacy_source_observation_key": source["source_observation_key"],
            "normalized_value": fact["normalized_value"],
            "canonical_unit": fact["canonical_unit"],
            "canonical_currency": fact["canonical_currency"],
            "direct_rank": fact["direct_rank"],
            "version_effective_scope_json": fact["version_effective_scope_json"],
            "logical_key_bucket": logical_bucket,
            "legacy_rowid": None,
            "fact_partition_locator": fact["fact_partition_locator"],
            "bucket_group": f"{logical_bucket:02d}",
        })
        grouped.setdefault(("source_key_locators", source_bucket), []).append({
            "legacy_source_observation_key": source["source_observation_key"],
            "corrected_source_observation_key": source["source_observation_key"],
            "corrected_base_key": source["source_observation_base_key"],
            "payload_sha256": source["record_hash"],
            "legacy_rowid": None,
            "domain": source["domain"],
            "partition_year": source["partition_year"],
            "dataset_name": source["dataset_name"],
            "key_bucket": source["key_bucket"],
            "source_partition_locator": source["source_partition_locator"],
            "bucket_group": f"{source_bucket:02d}",
        })
    written: list[Path] = []
    fact_output_paths: list[Path] = []
    source_output_paths: list[Path] = []
    for (layer, bucket), rows in sorted(grouped.items()):
        schema_source = _schema_file(predecessor, f"metadata/{layer}/bucket_group=*/*.parquet")
        target = successor / f"metadata/{layer}/bucket_group={bucket:02d}/part-continuing-update-{delta_tag}.parquet"
        _write_with_schema(rows, schema_source, target)
        written.append(target)
    return written


def _write_query_to_schema(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    schema_source: Path | None,
    target: Path,
) -> bool:
    """Stream one DuckDB result into one schema-compatible Parquet member."""
    reader = connection.execute(query).fetch_record_batch(65_536)
    schema = pq.ParquetFile(schema_source).schema_arrow if schema_source is not None else reader.schema
    writer: pq.ParquetWriter | None = None
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    row_count = 0
    try:
        for batch in reader:
            table = pa.Table.from_batches([batch]).select(schema.names).cast(schema, safe=False)
            if table.num_rows == 0:
                continue
            if writer is None:
                target.parent.mkdir(parents=True, exist_ok=True)
                writer = pq.ParquetWriter(temporary, schema, compression="zstd", version="2.6")
            writer.write_table(table, row_group_size=65_536)
            row_count += table.num_rows
    finally:
        if writer is not None:
            writer.close()
    if row_count == 0:
        temporary.unlink(missing_ok=True)
        return False
    os.replace(temporary, target)
    return True


def _duckdb_path_list(paths: list[Path]) -> str:
    return "[" + ",".join(json.dumps(str(path)) for path in paths) + "]"


def _write_partitioned_query_stream(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    schema_source: Path | None,
    output_root: Path,
    layer: str,
    file_tag: str,
) -> list[Path]:
    """Stream one joined index query into bounded bucket writers."""
    reader = connection.execute(query).fetch_record_batch(65_536)
    schema = pq.ParquetFile(schema_source).schema_arrow if schema_source is not None else reader.schema
    writers: dict[str, tuple[pq.ParquetWriter, Path, Path]] = {}
    written: list[Path] = []
    try:
        for batch in reader:
            table = pa.Table.from_batches([batch]).select(schema.names).cast(schema, safe=False)
            bucket_values = table["bucket_group"].to_pylist()
            for bucket in sorted(set(str(value) for value in bucket_values)):
                # A Parquet hive partition may infer a numeric bucket even
                # when the originating SQL expression formatted it as text.
                bucket_value = int(bucket) if pa.types.is_integer(table["bucket_group"].type) else bucket
                mask = pc.equal(table["bucket_group"], bucket_value)
                part = table.filter(mask)
                if part.num_rows == 0:
                    continue
                target = output_root / layer / f"bucket_group={bucket}" / f"{file_tag}.parquet"
                entry = writers.get(bucket)
                if entry is None:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
                    writer = pq.ParquetWriter(temporary, schema, compression="zstd", version="2.6")
                    entry = (writer, temporary, target)
                    writers[bucket] = entry
                entry[0].write_table(part, row_group_size=65_536)
    finally:
        for writer, temporary, target in writers.values():
            writer.close()
            os.replace(temporary, target)
            written.append(target)
    return written


def _write_delta_indexes_from_files(
    predecessor: Path | None,
    successor: Path,
    fact_paths: list[Path],
    source_paths: list[Path],
    delta_tag: str,
    years: set[str] | None = None,
) -> list[Path]:
    """Build locator layers one year partition at a time.

    Facts and source observations share the economic-year partition boundary.
    Joining one year at a time keeps the hash state bounded; bucket parts are
    then concatenated without another financial join.
    """
    if not fact_paths:
        return []
    def partition_year(path: Path) -> str:
        for part in path.parts:
            if part.startswith("year="):
                return part.split("=", 1)[1]
        raise ValueError(f"index input has no partition year: {path}")

    facts_by_year = {partition_year(path): path for path in fact_paths}
    sources_by_year = {partition_year(path): path for path in source_paths}
    selected_years = sorted(set(facts_by_year) & set(sources_by_year))
    if years is not None:
        selected_years = [year for year in selected_years if year in years]
    if not selected_years:
        return []

    parts_root = successor.parent / f".index-parts-{delta_tag}"
    parts_root.mkdir(parents=True, exist_ok=True)
    layers = ("corrected_lineage", "logical_lineage_lookup", "logical_key_locators", "source_key_locators")
    try:
        for year in selected_years:
            connection = duckdb.connect(":memory:")
            spill_root = successor.parent / f".duckdb-index-spill-{delta_tag}-{year}"
            spill_root.mkdir(parents=True, exist_ok=True)
            try:
                connection.execute("PRAGMA memory_limit='1GB'")
                connection.execute(f"PRAGMA temp_directory={json.dumps(str(spill_root))}")
                connection.execute(
                    f"CREATE TEMP VIEW new_facts AS SELECT * FROM read_parquet({_duckdb_path_list([facts_by_year[year]])}, union_by_name=true)"
                )
                connection.execute(
                    f"CREATE TEMP VIEW new_sources AS SELECT * FROM read_parquet({_duckdb_path_list([sources_by_year[year]])}, union_by_name=true)"
                )
                common = """
            SELECT
              CAST(NULL AS BIGINT) AS old_lineage_rowid,
              s.source_observation_key AS legacy_source_observation_key,
              f.logical_fact_key AS legacy_logical_fact_key,
              s.source_observation_key AS corrected_source_observation_key,
              f.metric_id AS corrected_metric_id,
              f.normalized_value AS lineage_normalized_value,
              f.canonical_unit AS lineage_canonical_unit,
              f.canonical_currency AS lineage_canonical_currency,
              f.direct_rank,
              f.version_effective_scope_json,
              s.source_partition_locator,
              f.fact_partition_locator,
              'accepted_fact_lineage' AS lineage_classification,
              printf('%02d', abs(hash(s.source_observation_key)) % 64) AS bucket_group,
              f.logical_fact_key AS corrected_logical_fact_key
            FROM new_facts f
            JOIN new_sources s USING (source_observation_key)
        """
                queries = {
                    "corrected_lineage": common,
                    "logical_lineage_lookup": f"SELECT q.*, printf('%02d', abs(hash(q.corrected_logical_fact_key)) % 64) AS logical_bucket_group FROM ({common}) q",
                    "logical_key_locators": """
                SELECT f.logical_fact_key, f.logical_fact_base_key,
                  f.logical_fact_key AS legacy_logical_fact_key,
                  s.source_observation_key AS legacy_source_observation_key,
                  f.normalized_value, f.canonical_unit, f.canonical_currency,
                  f.direct_rank, f.version_effective_scope_json,
                  CAST(abs(hash(f.logical_fact_key)) % 64 AS UBIGINT) AS logical_key_bucket,
                  CAST(NULL AS BIGINT) AS legacy_rowid,
                  f.fact_partition_locator,
                  printf('%02d', abs(hash(f.logical_fact_key)) % 64) AS bucket_group
                FROM new_facts f JOIN new_sources s USING (source_observation_key)
            """,
                    "source_key_locators": """
                SELECT s.source_observation_key AS legacy_source_observation_key,
                  s.source_observation_key AS corrected_source_observation_key,
                  s.source_observation_base_key AS corrected_base_key,
                  s.record_hash AS payload_sha256,
                  CAST(NULL AS BIGINT) AS legacy_rowid,
                  s.domain, s.partition_year, s.dataset_name, s.key_bucket,
                  s.source_partition_locator,
                  printf('%02d', abs(hash(s.source_observation_key)) % 64) AS bucket_group
                FROM new_facts f JOIN new_sources s USING (source_observation_key)
            """,
                }
                for layer, query in queries.items():
                    schema_source = (_schema_file(predecessor, f"metadata/{layer}/bucket_group=*/*.parquet")
                                     if predecessor is not None else None)
                    _write_partitioned_query_stream(connection, query, schema_source, parts_root, layer, f"year-{year}")
            finally:
                connection.close()
                shutil.rmtree(spill_root, ignore_errors=True)

        written: list[Path] = []
        merge_connection = duckdb.connect(":memory:")
        try:
            merge_connection.execute("PRAGMA memory_limit='1GB'")
            for layer in layers:
                schema_source = (_schema_file(predecessor, f"metadata/{layer}/bucket_group=*/*.parquet")
                                 if predecessor is not None else None)
                for bucket_dir in sorted((parts_root / layer).glob("bucket_group=*")):
                    members = sorted(bucket_dir.glob("*.parquet"))
                    if not members:
                        continue
                    bucket = bucket_dir.name.split("=", 1)[1]
                    target = successor / f"metadata/{layer}/bucket_group={bucket}/part-continuing-update-{delta_tag}.parquet"
                    if _write_query_to_schema(merge_connection, f"SELECT * FROM read_parquet({_duckdb_path_list(members)})", schema_source, target):
                        written.append(target)
        finally:
            merge_connection.close()
        return written
    finally:
        shutil.rmtree(parts_root, ignore_errors=True)


def write_initial_equity_lookup_indexes(
    snapshot: Path,
    fact_paths: list[Path],
    source_paths: list[Path],
) -> list[Path]:
    """Give an initial snapshot the same locator closure as later Equity deltas.

    There is no predecessor schema on an empty installation.  The index
    queries above define the initial physical schema; subsequent updates
    inherit it from these immutable members.
    """
    return _write_delta_indexes_from_files(
        None, snapshot, fact_paths, source_paths, "first-install"
    )


def _unchanged_coverage_only_plan(plan_path: Path, plan: dict[str, Any], index: AcceptedChinaEquityEpisodeIndex, control: Path) -> bool:
    """Avoid a successor for an empty retry whose canonical coverage is equal.

    Acquisition still runs: an empty provider response is not a reason to skip
    a later retry. This only compares the completed plan with its immutable
    predecessor and never advances a watermark or declares gaps resolved.
    """
    if any(plan.get(name) for name in (
        "reality_change_count", "source_progress_changed", "financial_observations", "documents",
        "identity_resolutions", "identity_resolution", "existing_subject_reality_events",
    )):
        return False
    for family in ("daily_observations", "daily_source_details"):
        if bounded_payload_count(plan, family) or plan.get(family):
            return False
        if any(batch for batch in iter_plan_rows(plan_path, plan, family)):
            return False
    reference = plan.get("bounded_daily_payload") or {}
    if reference.get("coverage_evidence_relative_path"):
        resolved = resolve_payload_manifest(plan_path, plan)
        assert resolved is not None
        root, manifest = resolved
        coverage = root / reference["coverage_evidence_relative_path"]
        expected = manifest.get("coverage_evidence_sha256")
        if sha256_file(coverage) != expected or reference.get("coverage_evidence_sha256") != expected:
            raise ValueError("bounded plan coverage evidence is missing or changed")
    evidence_count = 0
    with closing(sqlite3.connect(control.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        for evidence in iter_plan_coverage(plan_path, plan):
            if evidence["subject_role"] not in {"instrument", "entity"}:
                return False
            binding = _resolve_plan_binding(index, plan, evidence["exchange"], evidence["code"], evidence["effective_at"])
            subject = binding.instrument_id if evidence["subject_role"] == "instrument" else binding.entity_id
            rows = connection.execute(
                "SELECT coverage_state,fact_count FROM coverage_summary "
                "WHERE universe IN ('a_share','CN_A_SHARE') AND subject_id=? AND metric_id=?",
                (subject, canonical_financial_metric(evidence["metric_id"])),
            ).fetchall()
            if len(rows) != 1:
                return False
            previous_state, count = rows[0]
            derived = derive_coverage_from_route_evidence(
                lifecycle_applicable=bool(evidence["lifecycle_applicable"]), route_attempt_status=evidence["route_attempt_status"],
                returned_usable_observation_count=int(count or 0), retained_source_contract_boundary=evidence.get("retained_source_contract_boundary"),
            )
            if derived != previous_state:
                return False
            evidence_count += 1
    declared = plan.get("coverage_evidence") or []
    declared_count = int(declared.get("count", 0)) if isinstance(declared, dict) else len(declared)
    if evidence_count != declared_count:
        raise ValueError("coverage-only plan evidence count mismatch")
    return True


def run_discovery_plan(
    plan_path: Path,
    output_root: Path,
    *,
    inject_failure_after: str | None = None,
) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    require_internal_plan(plan)
    plan_hash = sha256_file(plan_path)
    delta_tag = plan_hash[:12]
    output_root.mkdir(parents=True, exist_ok=True)
    result_path = output_root / "continuing_update_result_v1.json"
    if result_path.is_file():
        existing = json.loads(result_path.read_text(encoding="utf-8"))
        if existing.get("plan_sha256") != plan_hash:
            raise RuntimeError("completed update output belongs to a different discovery plan")
        return {**existing, "idempotent_rerun": True}

    index = AcceptedChinaEquityEpisodeIndex.load(Path(plan["lifecycle_owner_path"]), Path(plan["identity_reconciliation_path"]))
    predecessor_id = plan["predecessor_snapshot_id"]
    successor_id = plan["successor_snapshot_id"]
    predecessor = resolve_unpublished_snapshot_path(predecessor_id)
    successor = resolve_unpublished_snapshot_path(successor_id)
    control_source = Path(plan["predecessor_control_path"])
    control_target = Path(plan["successor_control_path"])
    checkpoint_path = output_root / "checkpoint.json"
    if _unchanged_coverage_only_plan(plan_path, plan, index, control_source):
        result = {"schema_version": "fr_a_share_foundation_continuing_update_result_v1", "plan_sha256": plan_hash,
                  "predecessor_snapshot_id": predecessor_id, "successor_snapshot_id": None, "no_op": True,
                  "reason": "canonical_coverage_unchanged_without_business_delta", "active_pointer_modified": False, "result": "PASS"}
        write_json_atomic(result_path, result)
        return result

    financial_inputs: list[tuple[dict[str, Any], Any]] = []
    financial_candidates: list[tuple[dict[str, Any], Any, str]] = []
    required: list[tuple[str, str, str]] = []
    canonical_locator_bytes_read = 0
    canonical_locator_files_read = 0
    skipped_existing_financial = 0
    for item in plan.get("financial_observations", []):
        raw = dict(item)
        binding = _resolve_plan_binding(index, plan, raw["exchange"], raw["code"], raw.get("identity_effective_at") or raw["period_end"])
        raw["metric_id"] = canonical_financial_metric(raw["metric_id"])
        raw["accounting_scope"] = raw.get("accounting_scope", "consolidated")
        logical_key = financial_logical_fact_key(
            binding.entity_id,
            raw["metric_id"],
            raw["period_end"],
            raw.get("version_effective_scope"),
        )
        financial_candidates.append((raw, binding, logical_key))
    existing_financial_keys, canonical_locator_bytes_read, canonical_locator_files_read = _canonical_financial_keys_exist(
        predecessor, [logical_key for _, _, logical_key in financial_candidates]
    )
    for raw, binding, logical_key in financial_candidates:
        if logical_key in existing_financial_keys:
            skipped_existing_financial += 1
            continue
        financial_inputs.append((raw, binding))
        required.append((binding.entity_id, raw["metric_id"], raw["accounting_scope"]))

    identity = InstallationIdentityState(resolve_identity_state_path(), resolve_identity_state_backup_root())
    identity_before = identity.assignment_count()
    financial_series, created = _ensure_financial_series(identity, required)
    identity_after = identity.assignment_count()
    write_json_atomic(checkpoint_path, {"completed": ["identity_ready"], "plan_sha256": plan_hash, "identity_assignments_after": identity_after})
    if inject_failure_after == "identity_ready":
        raise RuntimeError("controlled_failure_after_identity_ready")

    clone = clone_snapshot_from_manifest(predecessor_id, successor_id)
    if not control_target.is_file():
        _sqlite_backup(control_source, control_target)

    # Transform normalized payload chunks into bounded on-disk batches. The
    # old implementation retained every fact/source row in Python lists.
    stage_root = output_root / "bounded_materialization_v2"
    fact_stage: dict[str, list[Path]] = {}
    source_stage: dict[str, list[Path]] = {}
    stage_writers: dict[tuple[str, str], pq.ParquetWriter] = {}
    daily_fact_count = 0
    daily_source_count = 0
    daily_existing_skipped = 0
    coverage_stats: dict[tuple[str, str], dict[str, Any]] = {}
    # The control DB contains bounded series metadata.  Load it once rather
    # than issuing one unindexed relationship scan per instrument while
    # transforming tens of millions of daily rows.
    series_cache = _series_for_all_instruments(control_source)
    resolutions = list(plan.get("identity_resolutions") or ())
    if plan.get("identity_resolution"):
        resolutions.append(plan["identity_resolution"])
    resolution_by_listing = {row.get("listing_id"): row for row in resolutions}
    resolution_lookup: dict[tuple[str, str], tuple[dict[str, Any], ...]] = {}
    grouped_resolutions: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for resolution in resolutions:
        key = (
            str(resolution["exchange"]).upper(),
            normalize_listing_code(str(resolution["exchange"]).upper(), resolution["code"]),
        )
        grouped_resolutions.setdefault(key, []).append(resolution)
    resolution_lookup = {key: tuple(rows) for key, rows in grouped_resolutions.items()}
    binding_cache: dict[tuple[str, str], Any] = {}

    def resolve_cached(exchange: str, code: str, effective_at: str | None) -> Any:
        key = (str(exchange).upper(), normalize_listing_code(str(exchange).upper(), code))
        binding = binding_cache.get(key)
        if binding is None:
            binding = _resolve_plan_binding(index, plan, exchange, code, effective_at, resolution_lookup)
            binding_cache[key] = binding
        return binding
    with closing(sqlite3.connect(control_source)) as connection:
        old_coverage: dict[tuple[str, str], tuple[int, str | None]] = {
            (str(subject), str(metric)): (int(count or 0), str(max_date) if max_date else None)
            for subject, metric, count, max_date in connection.execute(
                "SELECT subject_id,metric_id,fact_count,max_date_or_period FROM coverage_summary WHERE universe IN ('a_share','CN_A_SHARE')"
            )
        }

    # A prior bounded run may have completed all staged payload writes but
    # failed during successor finalization.  Reuse that physically verified
    # staging rather than replaying tens of millions of transformations.
    staged_fact_paths = sorted(stage_root.glob("standard_facts/domain=equity/year=*/staged.parquet"))
    staged_source_paths = sorted(stage_root.glob("source_observations/domain=equity/year=*/staged.parquet"))
    resume_staged = False
    reuse_existing_materialization = False
    if staged_fact_paths and staged_source_paths:
        with closing(duckdb.connect(":memory:")) as staged_connection:
            staged_fact_count = int(staged_connection.execute(
                f"SELECT count(*) FROM read_parquet({_duckdb_path_list(staged_fact_paths)})"
            ).fetchone()[0])
            staged_source_count = int(staged_connection.execute(
                f"SELECT count(*) FROM read_parquet({_duckdb_path_list(staged_source_paths)})"
            ).fetchone()[0])
            expected_fact_count = bounded_payload_count(plan, "daily_observations")
            expected_source_count = expected_fact_count + bounded_payload_count(plan, "daily_source_details")
            resume_staged = staged_fact_count == expected_fact_count and staged_source_count == expected_source_count
            if resume_staged:
                fact_stage = {}
                source_stage = {}
                for path in staged_fact_paths:
                    fact_stage.setdefault(path.parent.name.split("=")[-1], []).append(path)
                for path in staged_source_paths:
                    source_stage.setdefault(path.parent.name.split("=")[-1], []).append(path)
                daily_fact_count = staged_fact_count
                daily_source_count = staged_source_count
                for subject_id, metric_id, count, min_time, max_time in staged_connection.execute(
                    f"SELECT subject_id,metric_id,count(*),min(economic_time),max(economic_time) "
                    f"FROM read_parquet({_duckdb_path_list(staged_fact_paths)}) GROUP BY subject_id,metric_id"
                ).fetchall():
                    coverage_stats[(str(subject_id), str(metric_id))] = {
                        "count": int(count), "min": str(min_time), "max": str(max_time),
                    }
    # The prior bounded attempt reached the end of materialization and index
    # generation, then failed while deriving coverage metadata.  Reuse that
    # physically complete unpublished successor rather than rewriting tens of
    # gigabytes or rebuilding the four locator layers.  This is deliberately
    # strict: all staged years, all four 64-bucket index layers, and the
    # document delta must already exist for this fast path to apply.
    if resume_staged:
        existing_delta_paths = sorted(successor.rglob(f"*{delta_tag}*.parquet"))
        expected_buckets = {f"bucket_group={bucket:02d}" for bucket in range(64)}
        existing_facts = sorted(successor.glob(f"standard_facts/domain=equity/year=*/part-continuing-update-{delta_tag}.parquet"))
        existing_sources = sorted(successor.glob(f"source_observations/domain=equity/year=*/part-continuing-update-{delta_tag}.parquet"))
        index_layers_complete = all(
            {
                path.parent.name
                for path in successor.glob(f"metadata/{layer}/bucket_group=*/part-continuing-update-{delta_tag}.parquet")
            }
            == expected_buckets
            for layer in ("corrected_lineage", "logical_lineage_lookup", "logical_key_locators", "source_key_locators")
        )
        document_delta = successor / f"metadata/document_lookup/part-continuing-update-{delta_tag}.parquet"
        reuse_existing_materialization = bool(
            existing_facts
            and len(existing_facts) == len(fact_stage)
            and existing_sources
            and len(existing_sources) == len(source_stage)
            and index_layers_complete
            and document_delta.is_file()
            and existing_delta_paths
        )
    # A valid First-Install predecessor may contain accepted Equity identity
    # and coverage gaps but no promoted Equity fact yet.  The first later
    # observation defines the physical daily schema without fabricating a
    # zero-date fact or a fake predecessor index member.
    prior_daily_fact_schema = next(iter(sorted(predecessor.glob("standard_facts/domain=equity/year=*/*.parquet"))), None)
    prior_daily_source_schema = next(iter(sorted(predecessor.glob("source_observations/domain=equity/year=*/*.parquet"))), None)
    if prior_daily_fact_schema is not None and prior_daily_source_schema is None:
        raise ValueError("Equity predecessor has facts without source schema ownership")
    def stage_rows(facts: list[dict[str, Any]], sources: list[dict[str, Any]], batch_no: int) -> None:
        del batch_no  # row groups are appended to one file per family/year
        for family, rows, target_map, relative_pattern in (
            ("facts", facts, fact_stage, "standard_facts/domain=equity/year={year}/staged.parquet"),
            ("sources", sources, source_stage, "source_observations/domain=equity/year={year}/staged.parquet"),
        ):
            by_year: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                by_year.setdefault(str(row["partition_year"]), []).append(row)
            for year, grouped in by_year.items():
                path = stage_root / relative_pattern.format(year=year)
                schema_path = prior_daily_fact_schema if family == "facts" else prior_daily_source_schema
                schema = pq.ParquetFile(schema_path).schema_arrow if schema_path is not None else pa.Table.from_pylist(grouped).schema
                key = (family, year)
                writer = stage_writers.get(key)
                if writer is None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    writer = pq.ParquetWriter(path, schema, compression="zstd", version="2.6")
                    stage_writers[key] = writer
                    target_map[year] = [path]
                writer.write_table(pa.Table.from_pylist(grouped, schema=schema))

    batch_facts: list[dict[str, Any]] = []
    batch_sources: list[dict[str, Any]] = []
    batch_no = 0
    for raw_batch in (() if resume_staged else iter_plan_rows(plan_path, plan, "daily_observations")):
        resolved_batch: list[tuple[dict[str, Any], Any, str, str, str]] = []
        for raw in raw_batch:
            binding = resolve_cached(raw["exchange"], raw["code"], raw["economic_time"])
            old = old_coverage.get((binding.instrument_id, raw["metric_id"]))
            if old and old[1] and str(raw["economic_time"]) <= old[1]:
                daily_existing_skipped += 1
                continue
            series = series_cache.get(binding.instrument_id, {})
            resolution = resolution_by_listing.get(binding.listing_id) or {}
            if resolution:
                series = {**resolution.get("series", {}), **series}
            family = raw["series_family"]
            if family not in series:
                raise KeyError(f"accepted daily series missing for {binding.instrument_id}: {family}")
            year = str(raw["economic_time"])[:4]
            fact_target = f"standard_facts/domain=equity/year={year}/part-continuing-update-{delta_tag}.parquet"
            source_target = f"source_observations/domain=equity/year={year}/part-continuing-update-{delta_tag}.parquet"
            resolved_batch.append((raw, binding, series[family], fact_target, source_target))
        fact_buckets = _duckdb_bucket_map([series_id for _, _, series_id, _, _ in resolved_batch], 128)
        source_buckets = _duckdb_bucket_map([raw["source_observation_key"] for raw, _, _, _, _ in resolved_batch], 128)
        for raw, binding, series_id, fact_target, source_target in resolved_batch:
            fact, source = _daily_fact_and_source(
                raw, binding, series_id, fact_target, source_target,
                fact_bucket=fact_buckets[series_id],
                source_bucket=source_buckets[raw["source_observation_key"]],
            )
            batch_facts.append(fact)
            batch_sources.append(source)
            daily_fact_count += 1
            daily_source_count += 1
            key = (binding.instrument_id, raw["metric_id"])
            stats = coverage_stats.setdefault(key, {"count": 0, "min": None, "max": None})
            stats["count"] += 1
            observed_time = str(raw["economic_time"])
            stats["min"] = observed_time if stats["min"] is None else min(stats["min"], observed_time)
            stats["max"] = observed_time if stats["max"] is None else max(stats["max"], observed_time)
        if len(batch_facts) >= 65_536:
            stage_rows(batch_facts, batch_sources, batch_no)
            batch_facts, batch_sources = [], []
            batch_no += 1
    for raw_batch in (() if resume_staged else iter_plan_rows(plan_path, plan, "daily_source_details")):
        resolved_sources: list[tuple[dict[str, Any], Any, str]] = []
        for raw in raw_batch:
            binding = resolve_cached(raw["exchange"], raw["code"], raw["economic_time"])
            year = str(raw["economic_time"])[:4]
            source_target = f"source_observations/domain=equity/year={year}/part-continuing-update-{delta_tag}.parquet"
            resolved_sources.append((raw, binding, source_target))
        source_buckets = _duckdb_bucket_map([str(raw["source_detail_key"]) for raw, _, _ in resolved_sources], 128)
        for raw, binding, source_target in resolved_sources:
            batch_sources.append(_daily_source_detail(raw, binding, source_target, source_bucket=source_buckets[str(raw["source_detail_key"])]))
            daily_source_count += 1
        if len(batch_sources) >= 65_536:
            stage_rows([], batch_sources, batch_no)
            batch_sources = []
            batch_no += 1
    if batch_facts or batch_sources:
        stage_rows(batch_facts, batch_sources, batch_no)

    for writer in stage_writers.values():
        writer.close()
    stage_writers.clear()

    financial_fact_rows: list[dict[str, Any]] = []
    financial_source_rows: list[dict[str, Any]] = []
    for raw, binding in financial_inputs:
        year = str(raw["period_end"])[:4]
        fact_target = f"standard_facts/domain=financial_statements/year={year}/part-continuing-update-{delta_tag}.parquet"
        source_target = f"source_observations/domain=financial_statements/year={year}/part-continuing-update-{delta_tag}.parquet"
        series_id = financial_series[(binding.entity_id, raw["metric_id"], raw["accounting_scope"])]
        financial_fact_rows.append(_fact_row(raw, binding, series_id, fact_target))
        financial_source_rows.append(_source_row(raw, binding, raw["metric_id"], source_target))

    written: list[Path] = []
    fact_output_paths: list[Path] = []
    source_output_paths: list[Path] = []
    for domain, facts, sources in (("financial_statements", financial_fact_rows, financial_source_rows),):
        if facts:
            for year in sorted({row["partition_year"] for row in facts}):
                fact_target = successor / f"standard_facts/domain={domain}/year={year}/part-continuing-update-{delta_tag}.parquet"
                source_target = successor / f"source_observations/domain={domain}/year={year}/part-continuing-update-{delta_tag}.parquet"
                _write_with_schema([row for row in facts if row["partition_year"] == year], _schema_file(predecessor, f"standard_facts/domain={domain}/year=*/*.parquet"), fact_target)
                _write_with_schema([row for row in financial_source_rows if row["partition_year"] == year], _schema_file(predecessor, f"source_observations/domain={domain}/year=*/*.parquet"), source_target)
                written.extend([fact_target, source_target])
                fact_output_paths.append(fact_target)
                source_output_paths.append(source_target)
    duck = duckdb.connect(":memory:")
    try:
        if reuse_existing_materialization:
            fact_output_paths = sorted(successor.glob(f"standard_facts/domain=equity/year=*/part-continuing-update-{delta_tag}.parquet"))
            source_output_paths = sorted(successor.glob(f"source_observations/domain=equity/year=*/part-continuing-update-{delta_tag}.parquet"))
            written.extend(sorted(successor.rglob(f"*{delta_tag}*.parquet")))
        else:
            for year, paths in sorted(fact_stage.items()):
                fact_target = successor / f"standard_facts/domain=equity/year={year}/part-continuing-update-{delta_tag}.parquet"
                source_target = successor / f"source_observations/domain=equity/year={year}/part-continuing-update-{delta_tag}.parquet"
                if _write_query_to_schema(duck, f"SELECT * FROM read_parquet({_duckdb_path_list(paths)})", prior_daily_fact_schema, fact_target):
                    written.append(fact_target)
                    fact_output_paths.append(fact_target)
                source_paths = source_stage.get(year, [])
                if source_paths and _write_query_to_schema(duck, f"SELECT * FROM read_parquet({_duckdb_path_list(source_paths)})", prior_daily_source_schema, source_target):
                    written.append(source_target)
                    source_output_paths.append(source_target)
            written.extend(_write_delta_indexes_from_files(
                predecessor if prior_daily_fact_schema is not None else None,
                successor, fact_output_paths, source_output_paths, delta_tag,
            ))
    finally:
        duck.close()

    document_rows, document_asset_stats = _materialize_document_rows(
        [dict(item) for item in plan.get("documents", [])], index, plan, resolution_lookup
    )
    if inject_failure_after == "document_assets_ready":
        raise RuntimeError("controlled_failure_after_document_assets_ready")
    if document_rows:
        target = successor / f"metadata/document_lookup/part-continuing-update-{delta_tag}.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(document_rows), target, compression="zstd", version="2.6")
        written.append(target)

    coverage_rows = []
    with closing(sqlite3.connect(control_source)) as connection:
        for evidence in iter_plan_coverage(plan_path, plan):
            binding = resolve_cached(evidence["exchange"], evidence["code"], evidence["effective_at"])
            metric = canonical_financial_metric(evidence["metric_id"])
            subject_id = binding.instrument_id if evidence["subject_role"] == "instrument" else binding.entity_id
            previous = connection.execute(
                "SELECT fact_count,min_date_or_period,max_date_or_period FROM coverage_summary WHERE universe='a_share' AND subject_id=? AND metric_id=?",
                (subject_id, metric),
            ).fetchone()
            stat = coverage_stats.get((subject_id, metric), {"count": 0, "times": []})
            new_times = ([stat["min"], stat["max"]] if stat.get("count") else []) if evidence["subject_role"] == "instrument" else [
                row["economic_time"] for row in financial_fact_rows if row["metric_id"] == metric and row["subject_id"] == subject_id
            ]
            previous_count = int(previous[0]) if previous else 0
            total_count = previous_count + int(stat.get("count", 0) if evidence["subject_role"] == "instrument" else len(new_times))
            all_times = ([str(previous[1])] if previous and previous[1] else []) + ([str(previous[2])] if previous and previous[2] else []) + new_times
            coverage_rows.append({
                "entity_id": subject_id,
                "metric_id": metric,
                "coverage_state": derive_coverage_from_route_evidence(
                    lifecycle_applicable=bool(evidence["lifecycle_applicable"]),
                    route_attempt_status=evidence["route_attempt_status"],
                    returned_usable_observation_count=total_count,
                    retained_source_contract_boundary=evidence.get("retained_source_contract_boundary"),
                ),
                "fact_count": total_count,
                "min_time": min(all_times) if all_times else None,
                "max_time": max(all_times) if all_times else None,
            })
    identity_resolutions = list(plan.get("identity_resolutions") or ())
    if plan.get("identity_resolution"):
        identity_resolutions.append(plan["identity_resolution"])
    _control_apply(control_target, financial_series, coverage_rows, identity_resolutions,
                   list(plan.get("existing_subject_reality_events", [])))

    financial_coverage_source = predecessor / "metadata/coverage/a_share_financial_coverage_derivation_v1.parquet"
    replacement = {
        (row["entity_id"], row["metric_id"]): row
        for row in coverage_rows
        if row["metric_id"].startswith("financial.")
    }
    if financial_coverage_source.is_file() and replacement:
        table_rows = pq.read_table(financial_coverage_source).to_pylist()
        evidence_by_key = {
            (
                resolve_cached(item["exchange"], item["code"], item["effective_at"]).entity_id,
                canonical_financial_metric(item["metric_id"]),
            ): item
            for item in iter_plan_coverage(plan_path, plan)
            if item["subject_role"] == "entity"
        }
        for row in table_rows:
            key = (row["entity_id"], row["metric_id"])
            if key not in replacement:
                continue
            update = replacement[key]
            evidence = evidence_by_key[key]
            row.update({
                "coverage_state": update["coverage_state"],
                "fact_count": update["fact_count"],
                "min_time": update["min_time"],
                "max_time": update["max_time"],
                "derivation_basis": evidence["evidence_basis"],
                "lifecycle_subject_applicable": evidence["lifecycle_applicable"],
                "source_route_attempted": evidence["route_attempt_status"] != "not_attempted",
                "manual_status_input": False,
            })
        coverage_target = successor / "metadata/coverage/a_share_financial_coverage_derivation_v1.parquet"
        coverage_target.unlink(missing_ok=True)
        _write_with_schema(table_rows, financial_coverage_source, coverage_target)
        written.append(coverage_target)

    predecessor_manifest = json.loads((predecessor / "metadata/corrected_candidate_manifest_v1.json").read_text(encoding="utf-8"))
    files_by_path = {row["relative_path"]: dict(row) for row in predecessor_manifest["files"]}
    for path in written:
        row = _manifest_row(path, successor)
        row["created_at_utc"] = plan["created_at_utc"]
        files_by_path[row["relative_path"]] = row
    files = sorted(files_by_path.values(), key=lambda row: row["relative_path"])
    manifest = dict(predecessor_manifest)
    manifest.update({
        "schema_version": "fr_a_share_foundation_continuing_successor_manifest_v1",
        "snapshot_id": successor_id,
        "predecessor_snapshot_id": predecessor_id,
        "publication_state": "unpublished_continuing_update",
        "files": files,
        "file_count": len(files),
        "compressed_bytes": sum(int(row["byte_count"]) for row in files),
        "accepted_fact_output_count": int(predecessor_manifest["accepted_fact_output_count"]) + daily_fact_count + len(financial_fact_rows),
        "source_observation_count": int(predecessor_manifest["source_observation_count"]) + daily_source_count + len(financial_source_rows),
        "created_at_utc": plan["created_at_utc"],
    })
    manifest = reconcile_manifest_aggregate_counts(manifest)
    manifest_path = successor / "metadata/corrected_candidate_manifest_v1.json"
    write_json_atomic(manifest_path, manifest)
    result = {
        "schema_version": "fr_a_share_foundation_continuing_update_result_v1",
        "plan_sha256": plan_hash,
        "predecessor_snapshot_id": predecessor_id,
        "successor_snapshot_id": successor_id,
        "daily_fact_rows": daily_fact_count,
        "financial_fact_rows": len(financial_fact_rows),
        "source_observation_rows": daily_source_count + len(financial_source_rows),
        "lineage_rows": daily_fact_count + len(financial_fact_rows),
        "document_rows": len(document_rows),
        **document_asset_stats,
        "daily_existing_rows_skipped": daily_existing_skipped,
        "financial_existing_rows_skipped": skipped_existing_financial,
        "identity_assignments_before": identity_before,
        "identity_assignments_after": identity_after,
        "identity_assignments_created": created,
        "coverage_counts": dict(sorted(Counter(row["coverage_state"] for row in coverage_rows).items())),
        "canonical_financial_locator_bytes_read": canonical_locator_bytes_read,
        "canonical_financial_locator_files_read": canonical_locator_files_read,
        "legacy_financial_locator_rows_required": 0,
        "inherited_bulk_payload_bytes_read": clone["inherited_bulk_payload_bytes_read"],
        "written_file_count": len(written),
        "manifest_sha256": sha256_file(manifest_path),
        "active_pointer_modified": False,
        "result": "PASS",
    }
    write_json_atomic(result_path, result)
    write_json_atomic(checkpoint_path, {"completed": ["identity_ready", "successor_materialized"], "plan_sha256": plan_hash, "identity_assignments_after": identity_after})
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-state", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--run-bounded-update", action="store_true")
    parser.add_argument("--run-discovery-plan", action="store_true")
    parser.add_argument("--refresh-db", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--work-package", type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--inject-failure-after")
    args = parser.parse_args()
    if args.check_state or args.preflight:
        print(json.dumps(current_foundation_state(), ensure_ascii=False, sort_keys=True))
        return 0
    if args.run_bounded_update or args.refresh_db or args.all:
        package = args.work_package or (Path(os.environ["FR_A_SHARE_UPDATE_WORK_PACKAGE"]) if "FR_A_SHARE_UPDATE_WORK_PACKAGE" in os.environ else DEFAULT_PACKAGE)
        if not package.is_file():
            print(json.dumps({"status": "no_pending_work_package", "expected_path": str(package)}, ensure_ascii=False))
            return 0
        result = run_work_package(package, args.output_root, inject_failure_after=args.inject_failure_after)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    if args.run_discovery_plan:
        if not args.work_package:
            parser.error("--run-discovery-plan requires --work-package")
        result = run_discovery_plan(args.work_package, args.output_root, inject_failure_after=args.inject_failure_after)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    parser.error("choose --check-state, --preflight, --run-bounded-update, --run-discovery-plan, or --refresh-db")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
