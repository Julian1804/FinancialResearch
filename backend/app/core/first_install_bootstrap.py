"""Software-only first-install authority for bounded Fund + Equity bootstrap.

The input is a normalized source package produced by the versioned production
source/evidence contract.  This owner performs no legacy-state discovery and
accepts no predecessor snapshot.  It allocates installation-local identities,
writes one immutable integrated snapshot, records truthful coverage, creates
the two validated heads, and can atomically publish the first serving release.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import pyarrow as pa
import pyarrow.parquet as pq

from backend.app.core.artifact_io import canonical_json, sha256_file, stable_key, utc_now, write_json_atomic
from backend.app.core.china_public_fund_query import CONTROL_RELATIVE, FUND_QUERY_CONTRACT, FUND_STATE_OWNER
from backend.app.core.china_public_fund_query_index import (
    ensure_fund_query_schema,
    rebuild_fund_search_index,
    replace_nonpromoted_interval_index,
)
from backend.app.core.china_equity_identifiers import normalize_listing_code
from backend.app.core.china_equity_materialization import equity_lookup_buckets, write_initial_equity_lookup_indexes
from backend.app.core.china_equity_source_semantics import mainland_share_type
from backend.app.core.desired_data_profile import DesiredDataProfile, DesiredDataProfileRepository
from backend.app.core.retained_consumer import SERVING_BINDING_SCHEMA, register_retained_consumer
from backend.app.core.snapshot_manifest import reconcile_manifest_aggregate_counts
from backend.app.core.semantic_control import (
    canonical_alias_record,
    canonical_locator_record,
    canonical_relationship_record,
    ensure_semantic_control_schema,
    register_alias,
    register_locator,
    register_relationship,
)
from backend.app.core.serving_publication import transition_active_release
from backend.app.core.serving_release import RELEASE_SCHEMA_V2, contract_content_hash, release_content_hash, verify_release_descriptor
from backend.app.core.subject_identity import InstallationIdentityState
from backend.app.core.incremental_control import ensure_control_watermark_schema
from backend.app.core.validated_update_repository import ValidatedUpdateHead, ValidatedUpdateRepository


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_CONTRACT_PATH = PROJECT_ROOT / "config" / "fr_first_install_source_contract.json"
SOURCE_PACKAGE_SCHEMA = "fr_first_install_normalized_source_package_v1"
MANIFEST_RELATIVE = "metadata/corrected_candidate_manifest_v1.json"
COVERAGE_RELATIVE = "metadata/bootstrap/coverage_contract_v1.json"
FUND_IDENTITY_RELATIVE = "metadata/china_public_fund/authoritative_identity_owner_v1.json"
FUND_REALITY_RELATIVE = "metadata/china_public_fund/authoritative_reality_owner_v1.json"
FUND_CURRENT_LISTINGS_RELATIVE = "metadata/china_public_fund/authoritative_current_exchange_listings_v1.ndjson"
EQUITY_REALITY_RELATIVE = "metadata/a_share_update/authoritative_reality_owner_v1.ndjson"
EQUITY_IDENTITY_RELATIVE = "metadata/a_share_update/authoritative_identity_reconciliation_v1.json"
EQUITY_STATE_RELATIVE = "metadata/a_share_update/validated_update_state_v1.json"
FUND_DOMAIN = "funds_etfs"
EQUITY_DOMAIN = "equity"


class FirstInstallBootstrapError(RuntimeError):
    pass


def _listing_code(venue: Any, value: Any) -> str:
    try:
        return normalize_listing_code(venue, value)
    except ValueError as exc:
        raise FirstInstallBootstrapError(str(exc)) from exc


@dataclass(frozen=True)
class FirstInstallPaths:
    snapshots_root: Path
    identity_path: Path
    identity_backup_root: Path
    control_database: Path
    active_pointer: Path
    release_registry_root: Path

    def snapshot(self, snapshot_id: str) -> Path:
        return self.snapshots_root / snapshot_id


def load_source_contract(path: Path = SOURCE_CONTRACT_PATH) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != "fr_first_install_source_contract_v1":
        raise FirstInstallBootstrapError("unsupported first-install source contract")
    return value


def _require_package(profile: DesiredDataProfile, package: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(package)
    contract = load_source_contract()
    if value.get("schema_version") != SOURCE_PACKAGE_SCHEMA:
        raise FirstInstallBootstrapError("unsupported normalized source package")
    if (
        value.get("source_contract_id") != profile.source_contract_id
        or value.get("source_contract_version") != profile.source_contract_version
        or value.get("source_contract_id") != contract["contract_id"]
        or value.get("source_contract_version") != contract["contract_version"]
    ):
        raise FirstInstallBootstrapError("Desired Data Profile and source package contract differ")
    profile.validate()
    enabled = {scope.universe: scope for scope in profile.scopes if scope.state == "enabled"}
    if not enabled:
        raise FirstInstallBootstrapError("bootstrap has no enabled Desired Data Profile scope")
    if any(scope.full_available_history for scope in enabled.values()):
        raise FirstInstallBootstrapError(
            "source contract cannot validate full available history from an as-of-date package"
        )
    unsupported_modes = sorted({scope.population_mode for scope in enabled.values()} - set(contract["bootstrap_population_modes"]))
    if unsupported_modes:
        raise FirstInstallBootstrapError(f"source contract cannot execute population modes: {unsupported_modes}")
    unsupported_families = sorted({
        family
        for scope in enabled.values()
        for family in scope.data_families
        if family not in contract["universes"][scope.universe]["supported_data_families"]
    })
    if unsupported_families:
        raise FirstInstallBootstrapError(f"source contract cannot execute data families: {unsupported_families}")
    package_population = list(value.get("population") or [])
    selectors = [
        (scope.universe, str(row.get("venue") or ""), _listing_code(row.get("venue"), row.get("code")), str(row.get("listing_start") or ""))
        for scope in enabled.values()
        for row in scope.population_spec.get("selectors", [])
    ]
    population_keys = {
        (str(row.get("universe")), str(row.get("venue")), _listing_code(row.get("venue"), row.get("code")), str(row.get("listing_start") or ""))
        for row in package_population
    }
    matched_population = [
        [key for key in population_keys if key[:3] == selector[:3] and (not selector[3] or key[3] == selector[3])]
        for selector in selectors
    ]
    explicit_keys = {key for key in population_keys if enabled[key[0]].population_mode == "explicit_selection"}
    if (
        len(selectors) != len(explicit_keys)
        or any(len(matches) != 1 for matches in matched_population)
        or {matches[0] for matches in matched_population} != explicit_keys
    ):
        raise FirstInstallBootstrapError("source package population differs from the explicit requested denominator")
    for universe, scope in enabled.items():
        if scope.population_mode == "explicit_selection":
            continue
        definition = (value.get("population_definition") or {}).get(universe)
        if not definition or definition.get("population_mode") != scope.population_mode:
            raise FirstInstallBootstrapError("discovered population lacks a bound source definition")
        rows = [row for row in package_population if row["universe"] == universe]
        if int(definition.get("discovered_episode_count", -1)) != len(rows):
            raise FirstInstallBootstrapError("discovered population count differs from source definition")
        requested_venues = set(scope.population_spec.get("venues") or contract["universes"][universe]["bootstrap_executable_venues"])
        requested_codes = {
            _listing_code(venue, code)
            for venue in requested_venues
            for code in scope.population_spec.get("codes") or []
        }
        if set(definition.get("requested_venues") or []) != requested_venues:
            raise FirstInstallBootstrapError("discovered population venue scope differs from profile")
        definition_codes = {
            _listing_code(venue, code)
            for venue in requested_venues
            for code in definition.get("requested_codes") or []
        }
        if definition_codes != requested_codes:
            raise FirstInstallBootstrapError("discovered population code scope differs from profile")
        if definition.get("requested_interval") != {
            "start": scope.history_start, "end": scope.history_end,
            "full_available_history": scope.full_available_history,
        }:
            raise FirstInstallBootstrapError("discovered population history interval differs from profile")
        if any(
            row["venue"] not in requested_venues
            or requested_codes and _listing_code(row["venue"], row["code"]) not in requested_codes
            for row in rows
        ):
            raise FirstInstallBootstrapError("discovered population row lies outside requested scope")
        if scope.population_mode == "current_population" and any(row.get("listing_end") for row in rows):
            raise FirstInstallBootstrapError("current population contains a terminated listing episode")
        if scope.population_mode == "historical_interval_population" and any(
            str(row.get("listing_start") or "") > str(scope.history_end)
            or row.get("listing_end") and str(row["listing_end"]) < str(scope.history_start)
            for row in rows
        ):
            raise FirstInstallBootstrapError("historical population contains a non-intersecting listing episode")
    if len(population_keys) != len(package_population):
        raise FirstInstallBootstrapError("source package population contains duplicate listing episodes")
    for row in package_population:
        universe = str(row.get("universe"))
        venue = str(row.get("venue"))
        if (
            universe not in enabled
            or venue not in contract["universes"][universe]["identity_authorities"]
            or venue not in contract["universes"][universe]["bootstrap_executable_venues"]
        ):
            raise FirstInstallBootstrapError("population row is outside the enabled source contract")
        if venue == "HKEX" and row.get("current_identity_resolution") != "accepted_current_economic_security":
            raise FirstInstallBootstrapError("HKEX provider candidate is not an accepted economic identity")
        if universe == "CN_A_SHARE" and venue in {"SSE", "SZSE", "BSE"}:
            expected_share_type = mainland_share_type(venue, str(row["code"]))
            if str(row.get("share_type") or expected_share_type) != expected_share_type:
                raise FirstInstallBootstrapError("Mainland Equity share classification conflicts with venue/code contract")
        accepted_unknown_hkex = (
            venue == "HKEX" and not row.get("listing_start")
            and row.get("current_identity_resolution") == "accepted_current_economic_security"
            and bool(row.get("accepted_listing_id"))
            and (row.get("listing_start_boundary") or {}).get("status") == "unknown"
            and row.get("observation_attribution") == "unique_current_episode_in_accepted_graph"
        )
        if (not row.get("listing_start") and not accepted_unknown_hkex) or not row.get("evidence_refs"):
            raise FirstInstallBootstrapError("population row lacks authoritative lifecycle evidence")
        if row.get("listing_end") and row.get("listing_start") and str(row["listing_end"]) < str(row["listing_start"]):
            raise FirstInstallBootstrapError("population listing lifecycle is reversed")
        if universe == "CN_PUBLIC_FUND" and (not row.get("fund_product_id") or not row.get("contract_effective_date")):
            raise FirstInstallBootstrapError("Fund population lacks regulator product/share-class identity evidence")
    observations = list(value.get("observations") or [])
    observation_keys = [str(row.get("observation_key") or "") for row in observations]
    if len(set(observation_keys)) != len(observation_keys):
        raise FirstInstallBootstrapError("source package contains duplicate observation keys")
    blocked_keys = {
        str(key)
        for gap in value.get("gaps") or []
        if gap.get("gap_type") in {"identity_blocked", "semantic_conflict", "validation_failed"}
        for key in gap.get("observation_keys") or []
    }
    logical_observations: dict[tuple[str, str, str, str, str, str], tuple[Any, ...]] = {}
    for row in observations:
        key = str(row.get("observation_key") or "")
        listing_key = (
            str(row.get("universe")), str(row.get("venue")),
            _listing_code(row.get("venue"), row.get("code")), str(row.get("listing_start") or ""),
        )
        if not key or key in blocked_keys:
            raise FirstInstallBootstrapError("identity-blocked observations cannot be promoted")
        if row.get("binding_status") != "identity_resolved" or listing_key not in population_keys:
            raise FirstInstallBootstrapError("observation has no unique accepted listing-episode binding")
        population = next(
            item for item in package_population
            if (str(item.get("universe")), str(item.get("venue")), _listing_code(item.get("venue"), item.get("code")), str(item.get("listing_start") or "")) == listing_key
        )
        economic_time = str(row.get("economic_time") or "")
        if (population.get("listing_start") and economic_time < str(population["listing_start"])) or (population.get("listing_end") and economic_time > str(population["listing_end"])):
            raise FirstInstallBootstrapError("observation falls outside its accepted listing lifecycle")
        requested_scope = enabled[listing_key[0]]
        if not requested_scope.full_available_history and not (
            str(requested_scope.history_start) <= economic_time <= str(requested_scope.history_end)
        ):
            raise FirstInstallBootstrapError("observation falls outside the requested history interval")
        universe_contract = contract["universes"][listing_key[0]]
        if row.get("metric_id") not in universe_contract["supported_metrics"]:
            raise FirstInstallBootstrapError("observation metric is outside the source contract")
        if row.get("source_provider") not in universe_contract["fact_sources"]:
            raise FirstInstallBootstrapError("observation provider is outside the source contract")
        if not row.get("source_trace"):
            raise FirstInstallBootstrapError("observation lacks direct source trace")
        logical_key = (*listing_key, str(row["metric_id"]), economic_time)
        signature = (row.get("value"), row.get("unit"), row.get("currency"))
        if logical_key in logical_observations:
            if logical_observations[logical_key] != signature:
                raise FirstInstallBootstrapError("source package contains a semantic value conflict")
            raise FirstInstallBootstrapError("source package contains duplicate logical observations")
        logical_observations[logical_key] = signature
    source_details = list(value.get("source_details") or [])
    detail_keys = [str(row.get("source_detail_key") or "") for row in source_details]
    if not all(detail_keys) or len(set(detail_keys)) != len(detail_keys):
        raise FirstInstallBootstrapError("source package contains missing or duplicate source-detail keys")
    for row in source_details:
        listing_key = (
            str(row.get("universe")), str(row.get("venue")),
            _listing_code(row.get("venue"), row.get("code")), str(row.get("listing_start") or ""),
        )
        if row.get("promotion_status") != "source_detail_only":
            raise FirstInstallBootstrapError("source detail cannot request standard-fact promotion")
        if row.get("binding_status") != "identity_resolved" or listing_key not in population_keys:
            raise FirstInstallBootstrapError("source detail has no unique accepted listing-episode binding")
        economic_time = str(row.get("economic_time") or "")
        population = next(
            item for item in package_population
            if (str(item.get("universe")), str(item.get("venue")), _listing_code(item.get("venue"), item.get("code")), str(item.get("listing_start") or "")) == listing_key
        )
        if (population.get("listing_start") and economic_time < str(population["listing_start"])) or (population.get("listing_end") and economic_time > str(population["listing_end"])):
            raise FirstInstallBootstrapError("source detail falls outside its accepted listing lifecycle")
        scope = enabled[listing_key[0]]
        if not (str(scope.history_start) <= economic_time <= str(scope.history_end)):
            raise FirstInstallBootstrapError("source detail falls outside the requested history interval")
        if not row.get("source_trace") or row.get("source_provider") not in contract["universes"][listing_key[0]]["fact_sources"]:
            raise FirstInstallBootstrapError("source detail lacks an accepted direct source trace")
    return value


def _decision(
    identity: InstallationIdentityState,
    *,
    subject_type: str,
    authority: str,
    identifier_type: str,
    identifier_value: str,
    scope: Mapping[str, Any],
    statement: str,
    economic_object_type: str,
    evidence_refs: Iterable[str],
    effective_start: str | None = None,
    effective_end: str | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    candidate = {
        "authority": authority,
        "identifier_type": identifier_type,
        "identifier_value": identifier_value,
        "scope": dict(scope),
    }
    try:
        return identity.resolve_accepted_identity([candidate], effective_at=effective_start)
    except KeyError:
        created = identity.create_decision(
            subject_type=subject_type,
            accepted_identity_statement=statement,
            economic_object_type=economic_object_type,
            provenance_refs=evidence_refs,
            decision_attributes=attributes,
        )
        identity.register_accepted_crosswalk(
            identity_decision_id=created["identity_decision_id"],
            subject_type=subject_type,
            subject_id=created["subject_id"],
            authority=authority,
            identifier_type=identifier_type,
            identifier_value=identifier_value,
            scope=scope,
            effective_start=effective_start,
            effective_end=effective_end,
            provenance_refs=evidence_refs,
        )
        return created


def _subject(
    decision: Mapping[str, Any], *, domain: str, universe: str, name: str,
    venue: str | None, start: str | None, end: str | None, extra: Mapping[str, Any] | None = None,
    projected_object_type: str | None = None,
) -> dict[str, Any]:
    market_jurisdiction = "HK" if venue == "HKEX" else "CN" if venue or universe == "Fund" else None
    return {
        "subject_type": decision["subject_type"], "subject_id": decision["subject_id"],
        "domain": domain, "legacy_alias": None, "market": market_jurisdiction, "venue": venue,
        "effective_start": start, "effective_end": end, "code_aliases_json": "[]",
        "attributes_json": canonical_json({
            "display_name": name, "economic_object_type": projected_object_type or decision["economic_object_type"],
            "identity_decision_object_type": decision["economic_object_type"],
            "identity_contract": "installation_local_standard_id_ready",
            "identity_decision_id": decision["identity_decision_id"],
            "region": "CN", "market_jurisdiction": market_jurisdiction,
            "jurisdiction": market_jurisdiction, "universe": universe, **dict(extra or {}),
        }),
        "resolution_status": "standard_id_ready", "updated_at_utc": utc_now(),
    }


def _member(path: Path, root: Path, *, layer_name: str, row_count: int) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    return {
        "partition_id": stable_key("partition", {"layer_name": layer_name, "relative_path": relative}),
        "layer_name": layer_name, "relative_path": relative, "row_count": row_count,
        "byte_count": path.stat().st_size, "schema_sha256": hashlib.sha256(path.suffix.encode()).hexdigest(),
        "content_sha256": sha256_file(path), "completed": True, "created_at_utc": utc_now(),
    }


def _write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    inferred = pa.Table.from_pylist(rows)
    # A first snapshot may contain only volume facts or source-detail rows.
    # Null-only optional columns still need a usable predecessor type when a
    # later ordinary Update first supplies currency, scale, or another value.
    schema = pa.schema([
        field.with_type(pa.string()) if pa.types.is_null(field.type) else field
        for field in inferred.schema
    ])
    pq.write_table(inferred.cast(schema), path, compression="zstd")


def _fact_rows(
    observations: Iterable[Mapping[str, Any]], bindings: Mapping[tuple[str, str, str, str, str], tuple[str, str]],
    *, source_contract_version: str,
    equity_identity: Mapping[tuple[str, str, str], Mapping[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    facts: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    for stored in observations:
        row = dict(stored)
        population_key = (str(row["universe"]), str(row["venue"]), _listing_code(row["venue"], row["code"]), str(row.get("listing_start") or ""), str(row["metric_id"]))
        subject_id, series_id = bindings[population_key]
        source_key = str(row["observation_key"])
        metric = str(row["metric_id"])
        economic_time = str(row["economic_time"])
        domain = FUND_DOMAIN if row["universe"] == "CN_PUBLIC_FUND" else EQUITY_DOMAIN
        unit = str(row.get("unit") or ("CNY" if metric not in {"market.volume", "market.turnover_rate"} else "count"))
        currency = row.get("currency", "CNY" if metric not in {"market.volume", "market.turnover_rate"} else None)
        # The accepted fact representation keeps decimal text in Parquet;
        # binary floats must not become the physical predecessor schema.
        value = str(row["value"])
        trace = dict(row["source_trace"])
        is_equity = row["universe"] == "CN_A_SHARE"
        accepted_equity = equity_identity[(str(row["venue"]), _listing_code(row["venue"], row["code"]), str(row.get("listing_start") or ""))] if is_equity else None
        fact_subject_type = "series" if is_equity else ("fund_share_class" if metric.startswith("fund.") else "listing")
        fact_subject_id = series_id if is_equity else subject_id
        if is_equity:
            logical_payload = {
                "economic_time": {"role": "observation_date", "value": economic_time},
                "fact_dimensions": {}, "metric_id": metric,
                "subject": {"series_id": series_id, "subject_id": series_id, "subject_type": "series"},
                "version_effective_scope": {},
            }
            logical_key = stable_key("logical_fact", logical_payload)
            logical_base = logical_key.replace("logical_fact:", "logical_fact_base:", 1)
            version_scope = {}
        else:
            fund_time = {"primary_role": "observation_date", "primary_value": economic_time}
            fund_subject = {"subject_id": subject_id, "subject_type": fact_subject_type}
            version_scope = {"source_version_scope": economic_time}
            logical_base = stable_key("logical_fact_base", {
                "economic_time": fund_time, "fact_dimensions": {}, "metric_id": metric,
                "subject": fund_subject,
            })
            logical_key = stable_key("logical_fact", {
                "economic_time": fund_time, "fact_dimensions": {}, "metric_id": metric,
                "subject": fund_subject, "unit": unit, "currency": currency,
                "scale": "1", "version_effective_scope": version_scope,
            })
        fact = {
            "logical_fact_key": logical_key,
            "logical_fact_base_key": logical_base, "record_hash": stable_key("record", {"source": source_key, "value": value}),
            "dataset_name": "first_install_bootstrap", "dataset_id": "first_install_bootstrap_v1",
            "source_family": str(row["source_provider"]), "metric_id": metric,
            "subject_type": fact_subject_type,
            "subject_id": fact_subject_id, "series_id": series_id, "economic_time": economic_time,
            "primary_time_role": "observation_date", "fact_dimensions_json": "{}",
            "series_dimensions_json": canonical_json({"adjustment_basis": "unadjusted"} if row["universe"] == "CN_A_SHARE" else {}),
            "version_effective_scope_json": canonical_json(version_scope),
            "normalized_value": value, "canonical_unit": unit, "canonical_currency": currency,
            "canonical_scale": "1", "normalization_evidence_json": canonical_json({"operation": "identity", "source_value": value, "source_contract_version": source_contract_version}),
            "source_trace_json": canonical_json(trace), "direct_rank": 1, "classification": "standard_fact",
            "year": int(economic_time[:4]), "source_observation_key": source_key,
            "source_domain": domain, "source_partition_year": int(economic_time[:4]),
            "source_subject_hash_bucket": None if is_equity else int(hashlib.sha256(fact_subject_id.encode()).hexdigest()[:4], 16) % 256,
            "domain": domain, "partition_year": int(economic_time[:4]), "fact_partition_locator": None,
        }
        facts.append(fact)
        source_record = dict(row.get("source_record") or {})
        source_rows.append({
            "source_observation_key": source_key,
            "source_observation_base_key": stable_key("source_observation_base", {"provider": row["source_provider"], "metric": metric, "code": row["code"], "date": economic_time}),
            "metric_id": metric, "record_hash": stable_key("source_record", {"source": source_key, "record": source_record}),
            "domain": domain, "dataset_name": "first_install_bootstrap",
            "entity_key": accepted_equity["instrument_id"] if accepted_equity else str(row["code"]),
            "subject_candidate": accepted_equity["instrument_id"] if accepted_equity else str(row["code"]),
            "event_date_or_period": economic_time,
            "partition_year": int(economic_time[:4]), "source_provider": str(row["source_provider"]),
            "source_interface": str(trace.get("source_interface") or "public_api"), "source_symbol": str(row["code"]),
            "source_field_locator": str(trace.get("source_field_locator") or metric),
            "raw_value_json": canonical_json(value), "raw_unit": unit, "raw_currency": currency,
            "raw_scale": "1", "source_trace_json": canonical_json(trace), "source_record_json": canonical_json(source_record),
            "first_seen_at_utc": utc_now(), "source_detail_semantic_state": "accepted_source_observation" if is_equity else "identity_resolved",
            "key_bucket": None if is_equity else int(hashlib.sha256(source_key.encode()).hexdigest()[:4], 16) % 256,
            "source_partition_locator": None,
        })
    fact_buckets = equity_lookup_buckets([row["series_id"] for row in facts if row["domain"] == EQUITY_DOMAIN])
    source_buckets = equity_lookup_buckets([row["source_observation_key"] for row in source_rows if row["domain"] == EQUITY_DOMAIN])
    for row in facts:
        if row["domain"] == EQUITY_DOMAIN:
            row["source_subject_hash_bucket"] = fact_buckets[row["series_id"]]
    for row in source_rows:
        if row["domain"] == EQUITY_DOMAIN:
            row["key_bucket"] = source_buckets[row["source_observation_key"]]
    return facts, source_rows


def _source_detail_rows(
    details: Iterable[Mapping[str, Any]],
    equity_identity: Mapping[tuple[str, str, str], Mapping[str, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stored in details:
        row = dict(stored)
        economic_time = str(row["economic_time"])
        trace = dict(row["source_trace"])
        source_key = str(row["source_detail_key"])
        source_record = dict(row.get("source_record") or {})
        domain = FUND_DOMAIN if row["universe"] == "CN_PUBLIC_FUND" else EQUITY_DOMAIN
        accepted_equity = equity_identity[(str(row["venue"]), _listing_code(row["venue"], row["code"]), str(row.get("listing_start") or ""))] if domain == EQUITY_DOMAIN else None
        rows.append({
            "source_observation_key": source_key,
            "source_observation_base_key": stable_key("source_observation_base", {
                "provider": row["source_provider"], "field": row["source_field"],
                "code": row["code"], "date": economic_time,
            }),
            "metric_id": str(row.get("metric_id") or "market.trade_amount"),
            "record_hash": stable_key("source_record", {"source": source_key, "record": source_record}),
            "domain": domain, "dataset_name": "first_install_bootstrap",
            "entity_key": accepted_equity["instrument_id"] if accepted_equity else str(row["code"]),
            "subject_candidate": accepted_equity["instrument_id"] if accepted_equity else str(row["code"]),
            "event_date_or_period": economic_time, "partition_year": int(economic_time[:4]),
            "source_provider": str(row["source_provider"]),
            "source_interface": str(row["source_interface"]),
            "source_symbol": str(row.get("source_symbol") or row["code"]),
            "source_field_locator": str(row["source_field"]),
            "raw_value_json": canonical_json(row["raw_value"]),
            "raw_unit": row.get("raw_unit"), "raw_currency": row.get("raw_currency"),
            "raw_scale": row.get("raw_scale"), "source_trace_json": canonical_json(trace),
            "source_record_json": canonical_json(source_record), "first_seen_at_utc": utc_now(),
            "source_detail_semantic_state": str(row["source_detail_semantic_state"]),
            "key_bucket": None if domain == EQUITY_DOMAIN else int(hashlib.sha256(source_key.encode()).hexdigest()[:4], 16) % 256,
            "source_partition_locator": None,
        })
    buckets = equity_lookup_buckets([row["source_observation_key"] for row in rows if row["domain"] == EQUITY_DOMAIN])
    for row in rows:
        if row["domain"] == EQUITY_DOMAIN:
            row["key_bucket"] = buckets[row["source_observation_key"]]
    return rows


def build_initial_snapshot(
    *,
    profile: DesiredDataProfile,
    source_package: Mapping[str, Any],
    snapshot_id: str,
    paths: FirstInstallPaths,
) -> dict[str, Any]:
    """Build one immutable first snapshot without consulting installed history."""
    package = _require_package(profile, source_package)
    contract = load_source_contract()
    root = paths.snapshot(snapshot_id)
    if root.exists():
        raise FirstInstallBootstrapError("bootstrap snapshot target already exists")
    if paths.active_pointer.exists():
        raise FirstInstallBootstrapError("first-install bootstrap refuses an installation with an active pointer")
    root.mkdir(parents=True)
    identity = InstallationIdentityState(paths.identity_path, paths.identity_backup_root, create=True)
    generation = identity.metadata()["database_generation_id"]
    subjects: list[dict[str, Any]] = []
    aliases: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    equity_graph_relationships: list[dict[str, Any]] = []
    equity_episodes: list[dict[str, Any]] = []
    equity_objects: list[dict[str, Any]] = []
    equity_identity_by_listing: dict[tuple[str, str, str], dict[str, str]] = {}
    fund_objects: list[dict[str, Any]] = []
    bindings: dict[tuple[str, str, str, str, str], tuple[str, str]] = {}
    observations = list(package.get("observations") or [])

    for population in package["population"]:
        universe = str(population["universe"]); venue = str(population["venue"])
        code = _listing_code(venue, population["code"]); start = population.get("listing_start")
        start_key = str(start or "")
        end = population.get("listing_end"); evidence = list(population["evidence_refs"])
        name = str(population.get("display_name") or code)
        # This frozen scope key uses `jurisdiction=CN` as the historical China
        # regional namespace. Changing it would break accepted crosswalk/UUID
        # reuse; subject geography is projected separately below.
        scope = {"jurisdiction": "CN", "venue": venue, "listing_start": start, "object_role": "exchange_listing"}
        if venue == "HKEX" and start is None:
            scope["accepted_listing_id"] = population["accepted_listing_id"]
        if universe == "CN_PUBLIC_FUND":
            fund_product = str(population["fund_product_id"])
            fund_scope = {"jurisdiction": "CN", "object_role": "fund_product"}
            share_scope = {"jurisdiction": "CN", "object_role": "fund_share_class", "csrc_eid_fund_id": fund_product}
            fund = _decision(identity, subject_type="fund", authority="CSRC_EID", identifier_type="public_fund_id", identifier_value=fund_product, scope=fund_scope, statement=f"China public Fund product {fund_product}", economic_object_type="china_public_fund_product", evidence_refs=evidence, effective_start=str(population["contract_effective_date"]))
            share = _decision(identity, subject_type="fund_share_class", authority="CSRC_EID", identifier_type="public_fund_code", identifier_value=code, scope=share_scope, statement=f"Share class {code} of public Fund {fund_product}", economic_object_type="china_public_fund_share_class", evidence_refs=evidence, effective_start=str(population["contract_effective_date"]))
            instrument = _decision(identity, subject_type="instrument", authority=venue, identifier_type="fund_security_code", identifier_value=code, scope={**scope, "fund_product_id": fund_product, "object_role": "tradable_fund_instrument"}, statement=f"{venue} tradable Fund security {code}", economic_object_type="china_exchange_tradable_fund_instrument", evidence_refs=evidence, effective_start=start, effective_end=end)
            listing = _decision(identity, subject_type="listing", authority=venue, identifier_type="listing_code", identifier_value=code, scope={**scope, "csrc_eid_fund_id": fund_product}, statement=f"{venue} Fund listing episode {code} from {start}", economic_object_type="china_exchange_fund_listing_or_counter", evidence_refs=evidence, effective_start=start, effective_end=end)
            subjects.extend([
                _subject(fund, domain=FUND_DOMAIN, universe="Fund", name=str(population.get("fund_name") or name), venue=None, start=str(population["contract_effective_date"]), end=None, extra={"csrc_eid_fund_id": fund_product}),
                _subject(share, domain=FUND_DOMAIN, universe="Fund", name=name, venue=None, start=str(population["contract_effective_date"]), end=None, extra={"csrc_eid_fund_id": fund_product}),
                _subject(instrument, domain=FUND_DOMAIN, universe="Fund", name=name, venue=venue, start=start, end=end),
                _subject(listing, domain=FUND_DOMAIN, universe="Fund", name=name, venue=venue, start=start, end=end, extra={"listing_start_date": start}),
            ])
            aliases.extend([
                canonical_alias_record(subject_type="fund", subject_id=fund["subject_id"], alias_type="public_fund_id", alias_value=fund_product, scope=fund_scope, effective_start=str(population["contract_effective_date"]), effective_end=None, provenance_refs=evidence),
                canonical_alias_record(subject_type="fund_share_class", subject_id=share["subject_id"], alias_type="public_fund_code", alias_value=code, scope=share_scope, effective_start=str(population["contract_effective_date"]), effective_end=None, provenance_refs=evidence),
                canonical_alias_record(subject_type="listing", subject_id=listing["subject_id"], alias_type="listing_code", alias_value=code, scope={**scope, "csrc_eid_fund_id": fund_product}, effective_start=start, effective_end=end, provenance_refs=evidence),
            ])
            relationships.extend([
                canonical_relationship_record(from_type="fund_share_class", from_id=share["subject_id"], to_type="fund", to_id=fund["subject_id"], relationship_type="share_class_of", definition_ref="FR_CHINA_PUBLIC_FUND_FOUNDATION#share_class_of", effective_start=str(population["contract_effective_date"]), effective_end=None, provenance_refs=evidence),
                canonical_relationship_record(from_type="instrument", from_id=instrument["subject_id"], to_type="fund_share_class", to_id=share["subject_id"], relationship_type="represents_share_class", definition_ref="FR_CHINA_PUBLIC_FUND_FOUNDATION#represents_share_class", effective_start=start, effective_end=end, provenance_refs=evidence),
                canonical_relationship_record(from_type="listing", from_id=listing["subject_id"], to_type="instrument", to_id=instrument["subject_id"], relationship_type="listed_as", definition_ref="FR_CHINA_PUBLIC_FUND_FOUNDATION#listed_as", effective_start=start, effective_end=end, provenance_refs=evidence),
            ])
            fund_objects.append({"venue": venue, "code": code, "fund_id": fund["subject_id"], "share_class_id": share["subject_id"], "instrument_id": instrument["subject_id"], "listing_id": listing["subject_id"], "listing_start": start, "listing_end": end, "evidence_refs": evidence})
            # Series ownership follows the selected supported family, not
            # whether the initial provider happened to return a fact.  A
            # share class with a truthful coverage gap must remain updatable.
            metrics = sorted(str(metric) for metric in contract["universes"][universe]["supported_metrics"])
            for metric in metrics:
                target_type, target_id = ("fund_share_class", share["subject_id"]) if metric.startswith("fund.") else ("listing", listing["subject_id"])
                series_scope = {"jurisdiction": "CN", "object_role": "canonical_series", "target_subject_id": target_id, "metric_id": metric}
                series = _decision(identity, subject_type="series", authority="FR", identifier_type="canonical_metric_series", identifier_value=f"{target_id}:{metric}", scope=series_scope, statement=f"Canonical {metric} Series for accepted {target_type} {target_id}", economic_object_type="canonical_metric_series", evidence_refs=[*evidence, "config/metrics_registry.json"])
                subjects.append(_subject(series, domain=FUND_DOMAIN, universe="Fund", name=f"{metric} Series", venue=None, start=None, end=None, extra={"metric_id": metric, "series_dimensions": {}}))
                relationships.append(canonical_relationship_record(from_type="series", from_id=series["subject_id"], to_type=target_type, to_id=target_id, relationship_type="series_of", definition_ref="FR_DATA_GUARDRAILS#series_of", effective_start=None, effective_end=None, provenance_refs=[*evidence, "config/metrics_registry.json"], attributes={"metric_id": metric, "series_dimensions": {}}))
                bindings[(universe, venue, code, start, metric)] = (target_id, series["subject_id"])
        else:
            episode_identity = str(population["accepted_listing_id"]) if venue == "HKEX" and start is None else f"{code}:{start}"
            episode_statement = f"{venue} accepted listing episode {episode_identity}" if start is None else f"{venue} listing episode {code} from {start}"
            entity = _decision(identity, subject_type="entity", authority=venue, identifier_type="issuer_listing_episode", identifier_value=episode_identity, scope={**scope, "object_role": "issuer"}, statement=f"Issuer owning {episode_statement}", economic_object_type="china_equity_issuer", evidence_refs=evidence, effective_start=start, effective_end=end)
            share_type = str(population.get("share_type") or ("HKEX_EQUITY" if venue == "HKEX" else "A"))
            if venue == "BSE":
                # BSE is a venue; the historical BSE share-type token is only
                # accepted at this input boundary and never projected anew.
                share_type = mainland_share_type(venue, code, share_type)
            security_classification = ("hkex_equity" if venue == "HKEX" else
                                       "b_share" if share_type == "B" else "a_share")
            equity_scope = ("china_hkex_equity" if venue == "HKEX" else
                            "china_b_share" if share_type == "B" else "china_a_share")
            instrument = _decision(identity, subject_type="instrument", authority=venue, identifier_type="equity_security_episode", identifier_value=episode_identity, scope={**scope, "object_role": "equity_instrument"}, statement=f"Equity instrument for {episode_statement}", economic_object_type=f"{equity_scope}_instrument", evidence_refs=evidence, effective_start=start, effective_end=end)
            listing = _decision(identity, subject_type="listing", authority=venue, identifier_type="listing_code", identifier_value=code, scope=scope, statement=f"{venue} Equity {episode_statement}", economic_object_type=f"{equity_scope}_listing", evidence_refs=evidence, effective_start=start, effective_end=end)
            subjects.extend([
                _subject(entity, domain=EQUITY_DOMAIN, universe="Equity", name=name, venue=None, start=start, end=end),
                _subject(instrument, domain=EQUITY_DOMAIN, universe="Equity", name=name, venue=venue, start=start, end=end,
                         projected_object_type=f"{equity_scope}_instrument", extra={"share_type": share_type,
                                                                                      "security_classification": security_classification,
                                                                                      "board": population.get("board")}),
                _subject(listing, domain=EQUITY_DOMAIN, universe="Equity", name=name, venue=venue, start=start, end=end,
                         projected_object_type=f"{equity_scope}_listing", extra={"share_type": share_type,
                                                                                 "security_classification": security_classification,
                                                                                 "board": population.get("board")}),
            ])
            episode_key = episode_identity if venue == "HKEX" and start is None else f"{venue}:{code}:{start}:{end or 'current'}"
            equity_episodes.append({"episode_evidence_key": episode_key, "exchange": venue,
                                    "security_code_at_cutoff": code, "security_name_at_cutoff": name,
                                    "code_aliases": [{"code": code, "effective_from": start, "effective_to": end}],
                                    "listing_start_date": start, "listing_end_date": end,
                                    "lifecycle_status": "terminated" if end else "current",
                                    "board": population.get("board"), "share_type": share_type,
                                    "security_classification": security_classification,
                                    "issuer_display_name": name, "evidence_refs": evidence,
                                    "economic_entity_decision_key": entity["identity_decision_id"],
                                    "economic_instrument_decision_key": instrument["identity_decision_id"]})
            # A later daily metric may first become available after T0; the
            # accepted instrument owns its selected family's Series already.
            metrics = sorted(str(metric) for metric in contract["universes"][universe]["supported_metrics"])
            families: dict[str, list[str]] = {}
            family_map = {"equity.open": "daily_ohlc", "equity.high": "daily_ohlc", "equity.low": "daily_ohlc", "equity.close": "daily_ohlc", "market.volume": "market_volume", "market.trade_amount": "market_trade_amount", "market.turnover_rate": "market_turnover_rate"}
            for metric in metrics:
                families.setdefault(family_map[metric], []).append(metric)
            accepted_series: list[dict[str, str]] = []
            for family, family_metrics in sorted(families.items()):
                series = _decision(identity, subject_type="series", authority="FR", identifier_type="canonical_equity_series", identifier_value=f"{listing['subject_id']}:{family}:unadjusted", scope={"jurisdiction": "CN", "listing_id": listing["subject_id"], "series_family": family, "adjustment_basis": "unadjusted"}, statement=f"Canonical unadjusted {family} Series for listing {listing['subject_id']}", economic_object_type="canonical_metric_series", evidence_refs=[*evidence, "config/metrics_registry.json"])
                subjects.append(_subject(series, domain=EQUITY_DOMAIN, universe="Equity", name=f"{family} Series", venue=venue, start=start, end=end, extra={"series_family": family, "series_dimensions": {"adjustment_basis": "unadjusted"}}))
                accepted_series.append({"series_family": family, "series_id": series["subject_id"]})
                parent = canonical_relationship_record(from_type="series", from_id=series["subject_id"], to_type="instrument", to_id=instrument["subject_id"], relationship_type="series_of", definition_ref="FR_DATA_GUARDRAILS#series_of", effective_start=start, effective_end=end, provenance_refs=evidence, attributes={"series_family": family})
                relationships.append(parent)
                equity_graph_relationships.append({**parent, "resolution_status": "standard_id_ready"})
                relation = canonical_relationship_record(from_type="series", from_id=series["subject_id"], to_type="listing", to_id=listing["subject_id"], relationship_type="quoted_on", definition_ref="FR_DATA_GUARDRAILS#quoted_on", effective_start=start, effective_end=end, provenance_refs=evidence, attributes={"series_family": family})
                relationships.append(relation)
                equity_graph_relationships.append({**relation, "resolution_status": "standard_id_ready"})
                for metric in family_metrics:
                    bindings[(universe, venue, code, start_key, metric)] = (listing["subject_id"], series["subject_id"])
            equity_objects.append({
                "episode_evidence_key": episode_key, "exchange": venue, "code": code,
                "entity_id": entity["subject_id"], "instrument_id": instrument["subject_id"],
                "listing_id": listing["subject_id"], "lifecycle_status": "terminated" if end else "current",
                "series": accepted_series,
            })
            equity_identity_by_listing[(venue, code, start_key)] = {
                "instrument_id": instrument["subject_id"],
                "listing_id": listing["subject_id"],
                "episode_evidence_key": episode_key,
            }

    facts, source_rows = _fact_rows(
        observations, bindings, source_contract_version=profile.source_contract_version,
        equity_identity=equity_identity_by_listing,
    )
    source_rows.extend(_source_detail_rows(package.get("source_details") or [], equity_identity_by_listing))
    members: list[dict[str, Any]] = []
    equity_fact_paths: list[Path] = []
    equity_source_paths: list[Path] = []
    for domain, domain_rows in ((FUND_DOMAIN, [row for row in facts if row["domain"] == FUND_DOMAIN]), (EQUITY_DOMAIN, [row for row in facts if row["domain"] == EQUITY_DOMAIN])):
        for year in sorted({row["year"] for row in domain_rows}):
            rows = [row for row in domain_rows if row["year"] == year]
            file_name = "part-00000.parquet" if domain == FUND_DOMAIN else "part-a-share.parquet"
            path = root / f"standard_facts/domain={'fund' if domain == FUND_DOMAIN else 'equity'}/year={year}/{file_name}"
            if domain == EQUITY_DOMAIN:
                for row in rows:
                    row["fact_partition_locator"] = path.relative_to(root).as_posix()
            _write_parquet(path, rows); members.append(_member(path, root, layer_name="standard_facts", row_count=len(rows)))
            if domain == EQUITY_DOMAIN:
                equity_fact_paths.append(path)
    for domain, domain_rows in ((FUND_DOMAIN, [row for row in source_rows if row["domain"] == FUND_DOMAIN]), (EQUITY_DOMAIN, [row for row in source_rows if row["domain"] == EQUITY_DOMAIN])):
        for year in sorted({row["partition_year"] for row in domain_rows}):
            rows = [row for row in domain_rows if row["partition_year"] == year]
            path = root / f"source_observations/domain={'fund' if domain == FUND_DOMAIN else 'equity'}/year={year}/part-00000.parquet"
            if domain == EQUITY_DOMAIN:
                for row in rows:
                    row["source_partition_locator"] = path.relative_to(root).as_posix()
            _write_parquet(path, rows); members.append(_member(path, root, layer_name="source_observations", row_count=len(rows)))
            if domain == EQUITY_DOMAIN:
                equity_source_paths.append(path)
    for path in write_initial_equity_lookup_indexes(root, equity_fact_paths, equity_source_paths):
        members.append(_member(path, root, layer_name="metadata", row_count=pq.ParquetFile(path).metadata.num_rows))

    subject_path = root / "metadata/subject_graph/subjects.parquet"
    relationship_path = root / "metadata/subject_graph/relationships.parquet"
    _write_parquet(subject_path, subjects)
    graph_relations = [*relationships]
    replacements = {row["relationship_id"]: row for row in equity_graph_relationships}
    graph_relations = [replacements.get(row["relationship_id"], row) for row in graph_relations]
    _write_parquet(relationship_path, graph_relations)
    members.extend([_member(subject_path, root, layer_name="metadata", row_count=len(subjects)), _member(relationship_path, root, layer_name="metadata", row_count=len(graph_relations))])

    equity_reality = root / EQUITY_REALITY_RELATIVE
    equity_reality.parent.mkdir(parents=True, exist_ok=True)
    equity_reality.write_text("".join(canonical_json(row) + "\n" for row in equity_episodes), encoding="utf-8")
    equity_identity = root / EQUITY_IDENTITY_RELATIVE
    write_json_atomic(equity_identity, {"schema_version": "fr_a_share_authoritative_identity_reconciliation_v1", "database_generation_id": generation, "objects": equity_objects, "result": "PASS"})
    fund_identity = root / FUND_IDENTITY_RELATIVE
    write_json_atomic(fund_identity, {"schema_version": "fr_china_public_fund_authoritative_identity_owner_v1", "database_generation_id": generation, "objects": fund_objects, "result": "PASS"})
    fund_current_listings = root / FUND_CURRENT_LISTINGS_RELATIVE
    fund_current_listings.parent.mkdir(parents=True, exist_ok=True)
    fund_listing_rows = [
        {
            "csrc_eid_fund_id": str(row.get("fund_product_id") or ""),
            "csrc_product_sequence": None,
            "exchange_code": _listing_code(row["venue"], row["code"]),
            "listing_date": row.get("listing_start"),
            "listing_name": row.get("fund_name") or row.get("display_name"),
            "manager_name": None,
            "observation_date": package["as_of_date"],
            "product_binding_status": "proved",
            "product_structure_code": None,
            "source_refs": list(row.get("evidence_refs") or []),
            "venue": row["venue"],
        }
        for row in package["population"] if row["universe"] == "CN_PUBLIC_FUND"
    ]
    fund_current_listings.write_text(
        "".join(canonical_json(row) + "\n" for row in sorted(fund_listing_rows, key=lambda item: (item["venue"], item["exchange_code"]))),
        encoding="utf-8",
    )
    fund_reality = root / FUND_REALITY_RELATIVE
    write_json_atomic(fund_reality, {
        "schema_version": "fr_china_public_fund_authoritative_reality_owner_v1",
        "database_generation_id": generation,
        "as_of_date": package["as_of_date"],
        "fund_products": len({str(row.get("fund_product_id") or "") for row in package["population"] if row["universe"] == "CN_PUBLIC_FUND"}),
        "fund_share_classes": len([row for row in package["population"] if row["universe"] == "CN_PUBLIC_FUND"]),
        "current_exchange_listings": len(fund_listing_rows),
        "authoritative_files": [{"relative_path": FUND_CURRENT_LISTINGS_RELATIVE, "bytes": fund_current_listings.stat().st_size, "sha256": sha256_file(fund_current_listings)}],
        "result": "PASS",
    })
    interval_coverage = []
    enabled_scopes = {scope.universe: scope for scope in profile.scopes if scope.state == "enabled"}
    for population in package["population"]:
        universe = str(population["universe"])
        scope = enabled_scopes[universe]
        code = _listing_code(population["venue"], population["code"])
        start = population.get("listing_start")
        rows = [
            row for row in observations
            if row["universe"] == universe and row["venue"] == population["venue"]
            and _listing_code(row["venue"], row["code"]) == code and row.get("listing_start") == start
        ]
        actual_dates = sorted({str(row["economic_time"]) for row in rows})
        supported_start = max(str(scope.history_start), start) if start else scope.history_start
        supported_end = min(str(scope.history_end), str(population["listing_end"])) if population.get("listing_end") else scope.history_end
        interval_coverage.append({
            "universe": universe, "venue": population["venue"], "code": code,
            "listing_start": start, "listing_end": population.get("listing_end"),
            "listing_start_boundary": population.get("listing_start_boundary") or ({"status": "exact", "date": start} if start else None),
            "requested_interval": {"start": scope.history_start, "end": scope.history_end,
                                   "full_available_history": scope.full_available_history},
            "lifecycle_intersection": {"start": supported_start, "end": supported_end}
            if supported_end is None or supported_start <= supported_end else None,
            "source_requested_interval": {"start": supported_start, "end": supported_end}
            if supported_end is None or supported_start <= supported_end else None,
            "source_reconstructable_interval": {"start": actual_dates[0], "end": actual_dates[-1]}
            if actual_dates else None,
            "validated_actual_interval": {"start": actual_dates[0], "end": actual_dates[-1]}
            if actual_dates else None,
            "validated_observation_date_count": len(actual_dates),
            "validated_observation_count": len(rows),
        })
    coverage = {
        "requested_scope": profile.payload(),
        "supported_scope": {"source_contract_id": profile.source_contract_id, "source_contract_version": profile.source_contract_version, "population_definition": package.get("population_definition") or {}, "population_count": len(package["population"])},
        "validated_actual_coverage": {"population_count": len(package["population"]), "observation_count": len(observations), "source_detail_count": len(package.get("source_details") or []), "fact_count": len(facts), "by_universe": {universe: {"population_count": sum(row["universe"] == universe for row in package["population"]), "fact_count": sum(row["universe"] == universe for row in observations)} for universe in ("CN_PUBLIC_FUND", "CN_A_SHARE")}},
        "population_interval_coverage": interval_coverage,
        "gaps": list(package.get("gaps") or []),
        "legacy_developer_state_used": False,
        "global_historical_completeness_claimed": False,
    }
    coverage_path = root / COVERAGE_RELATIVE
    write_json_atomic(coverage_path, {"schema_version": "fr_bootstrap_coverage_contract_v1", "snapshot_id": snapshot_id, "profile_id": profile.profile_id, **coverage})
    members.extend([
        _member(equity_reality, root, layer_name="metadata", row_count=len(equity_episodes)),
        _member(equity_identity, root, layer_name="metadata", row_count=1),
        _member(fund_identity, root, layer_name="metadata", row_count=1),
        _member(fund_current_listings, root, layer_name="metadata", row_count=len(fund_listing_rows)),
        _member(fund_reality, root, layer_name="metadata", row_count=1),
        _member(coverage_path, root, layer_name="metadata", row_count=1),
    ])

    fund_contract_path = root / FUND_QUERY_CONTRACT
    write_json_atomic(fund_contract_path, {"schema_version": "fr_china_public_fund_minimum_query_v1", "snapshot_id": snapshot_id, "database_generation_id": generation, "release_binding": "request_pinned_immutable_serving_release", "supported_metrics": ["fund.nav", "fund.accumulated_nav", "market.close_price", "market.volume", "market.trade_amount"]})
    fund_state = root / FUND_STATE_OWNER
    write_json_atomic(fund_state, {"schema_version": "fr_china_public_fund_validated_update_state_v1", "snapshot_id": snapshot_id, "database_generation_id": generation, "identity_owner_path": str(fund_identity), "identity_owner_sha256": sha256_file(fund_identity), "coverage_contract_relative_path": COVERAGE_RELATIVE, "predecessor_snapshot_id": None})
    equity_state = root / EQUITY_STATE_RELATIVE
    write_json_atomic(equity_state, {"schema_version": "fr_a_share_validated_update_state_v1", "snapshot_id": snapshot_id, "database_generation_id": generation, "identity_owner_path": str(equity_identity), "identity_owner_sha256": sha256_file(equity_identity), "coverage_contract_relative_path": COVERAGE_RELATIVE, "predecessor_snapshot_id": None})
    members.extend([_member(fund_contract_path, root, layer_name="metadata", row_count=1), _member(fund_state, root, layer_name="metadata", row_count=1), _member(equity_state, root, layer_name="metadata", row_count=1)])

    control = root / CONTROL_RELATIVE
    control.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(control)) as connection:
        ensure_semantic_control_schema(connection); ensure_fund_query_schema(connection)
        ensure_control_watermark_schema(connection)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS coverage_summary("
            "universe TEXT NOT NULL,subject_id TEXT NOT NULL,metric_id TEXT NOT NULL,"
            "coverage_state TEXT NOT NULL,fact_count INTEGER NOT NULL,"
            "min_date_or_period TEXT,max_date_or_period TEXT,"
            "PRIMARY KEY(universe,subject_id,metric_id,coverage_state))"
        )
        connection.execute("CREATE TABLE snapshot_catalog(snapshot_id TEXT PRIMARY KEY,predecessor_snapshot_id TEXT,created_at_utc TEXT)")
        connection.execute("CREATE TABLE partition_manifest(partition_id TEXT PRIMARY KEY,layer_name TEXT NOT NULL,relative_path TEXT NOT NULL UNIQUE,row_count INTEGER NOT NULL,byte_count INTEGER NOT NULL,content_sha256 TEXT NOT NULL,completed INTEGER NOT NULL)")
        connection.execute("INSERT INTO snapshot_catalog VALUES (?,?,?)", (snapshot_id, None, utc_now()))
        connection.executemany("INSERT INTO partition_manifest VALUES (?,?,?,?,?,?,?)", [(row["partition_id"], row["layer_name"], row["relative_path"], row["row_count"], row["byte_count"], row["content_sha256"], 1) for row in members])
        columns = tuple(subjects[0])
        connection.executemany(f"INSERT INTO subject_registry({','.join(columns)}) VALUES({','.join('?' for _ in columns)})", [tuple(row[column] for column in columns) for row in subjects])
        for row in aliases: register_alias(connection, row)
        for row in relationships: register_relationship(connection, row)
        for row in equity_graph_relationships:
            connection.execute(
                "UPDATE subject_relationship_registry SET resolution_status='standard_id_ready' WHERE relationship_id=?",
                (row["relationship_id"],),
            )
        fact_members = {row["relative_path"]: row for row in members if row["layer_name"] == "standard_facts"}
        equity_instruments = {row["listing_id"]: row["instrument_id"] for row in equity_objects}
        for key, (subject_id, series_id) in bindings.items():
            universe, _venue, _code, _start, metric = key
            is_equity = universe == "CN_A_SHARE"
            fact_subject = series_id if is_equity else subject_id
            matching = [fact for fact in facts if fact["subject_id"] == fact_subject and fact["metric_id"] == metric]
            if not is_equity and matching:
                connection.execute(
                    "INSERT OR REPLACE INTO control_series_watermark VALUES (?,?,?,?)",
                    ("fund_share_class" if metric.startswith("fund.") else "listing", subject_id,
                     metric, max(row["economic_time"] for row in matching)),
                )
            if is_equity and matching:
                connection.execute(
                    "INSERT OR REPLACE INTO coverage_summary VALUES (?,?,?,?,?,?,?)",
                    ("a_share", equity_instruments[subject_id], metric, "available", len(matching),
                     min(row["economic_time"] for row in matching),
                     max(row["economic_time"] for row in matching)),
                )
            for relative, member in fact_members.items():
                year = int(relative.split("year=", 1)[1].split("/", 1)[0])
                dated = [row for row in matching if row["year"] == year]
                if not dated: continue
                register_locator(connection, canonical_locator_record(snapshot_id=snapshot_id, layer_name="standard_facts", subject_type="series" if is_equity else ("fund_share_class" if metric.startswith("fund.") else "listing"), subject_id=fact_subject, metric_id=metric, scope={"universe": "Fund" if universe == "CN_PUBLIC_FUND" else "Equity", "jurisdiction": "CN"}, time_start=min(row["economic_time"] for row in dated), time_end=max(row["economic_time"] for row in dated), relative_path=relative, content_sha256=member["content_sha256"], row_group_start=0, row_group_end=0))
        connection.execute("INSERT OR REPLACE INTO control_watermark_state VALUES (1,1)")
        rebuild_fund_search_index(connection, snapshot_id)
        replace_nonpromoted_interval_index(connection, snapshot_id, [{"external_code": gap.get("code"), "metric_id": gap.get("metric_id"), "time_start": gap.get("time_start"), "time_end": gap.get("time_end"), "row_count": gap.get("row_count", 0), "reason": gap["gap_type"], "evidence_refs": gap.get("evidence_refs", [])} for gap in package.get("gaps") or [] if gap.get("universe") == "CN_PUBLIC_FUND"])
        connection.commit()
    members.append(_member(control, root, layer_name="metadata", row_count=1))
    manifest_path = root / MANIFEST_RELATIVE
    manifest = {"schema_version": "fr_corrected_candidate_manifest_v1", "snapshot_id": snapshot_id, "database_generation_id": generation, "predecessor_snapshot_id": None, "reality_cutoff_date": str(package["as_of_date"]), "source_contract_id": profile.source_contract_id, "source_contract_version": profile.source_contract_version, "files": sorted(members, key=lambda row: row["relative_path"]), "file_count": len(members), "compressed_bytes": sum(int(row["byte_count"]) for row in members), "row_count": sum(int(row["row_count"]) for row in members if row["layer_name"] in {"standard_facts", "source_observations"}), "canonical_china_public_fund_fact_rows": sum(row["universe"] == "CN_PUBLIC_FUND" for row in observations), "china_public_fund_unresolved_history_rows": 0}
    manifest = reconcile_manifest_aggregate_counts(manifest)
    write_json_atomic(manifest_path, manifest)
    manifest_sha = sha256_file(manifest_path)

    profile_repository = DesiredDataProfileRepository(paths.control_database)
    profile_repository.put(profile)
    recorded_coverage = profile_repository.record_coverage(snapshot_id, profile.profile_id, coverage)
    repository = ValidatedUpdateRepository(paths.control_database, identity_path=paths.identity_path, snapshot_root=paths.snapshot)
    common = {"database_generation_id": generation, "snapshot_id": snapshot_id, "snapshot_manifest_sha256": manifest_sha, "authoritative_cutoff": str(package["as_of_date"]), "predecessor_snapshot_id": None, "transaction_id": snapshot_id, "run_id": str(package["run_id"])}
    repository.bootstrap(ValidatedUpdateHead(universe="CN_PUBLIC_FUND", reality_owner_path=str(fund_identity), reality_owner_sha256=sha256_file(fund_identity), state_path=str(fund_state), state_sha256=sha256_file(fund_state), **common))
    repository.bootstrap(ValidatedUpdateHead(universe="CN_A_SHARE", reality_owner_path=str(equity_reality), reality_owner_sha256=sha256_file(equity_reality), state_path=str(equity_state), state_sha256=sha256_file(equity_state), **common))
    return {"snapshot_id": snapshot_id, "snapshot_root": str(root), "manifest_sha256": manifest_sha, "database_generation_id": generation, "coverage": recorded_coverage, "fact_count": len(facts), "population_count": len(package["population"])}


def publish_initial_snapshot(
    *,
    build_result: Mapping[str, Any],
    paths: FirstInstallPaths,
    committed_at_utc: str,
    publication_operation_id: str | None = None,
    failure_point: str | None = None,
) -> dict[str, Any]:
    """Register and atomically publish the first release on an empty install."""
    snapshot_id = str(build_result["snapshot_id"]); root = paths.snapshot(snapshot_id)
    manifest_sha = str(build_result["manifest_sha256"]); generation = str(build_result["database_generation_id"])
    manifest = json.loads((root / MANIFEST_RELATIVE).read_text(encoding="utf-8"))
    component_proof = {"component_member_count": len(manifest["files"]), "identical_member_count": len(manifest["files"]), "merged_shared_owner_paths": []}
    fund_contract = json.loads((root / FUND_QUERY_CONTRACT).read_text(encoding="utf-8"))
    equity_contract = {"schema_version": "china_equity_minimum_daily_query_v1", "supported_adjustment_bases": ["unadjusted"], "release_binding": "request_pinned_immutable_serving_release"}
    release_id = f"release_{snapshot_id}"
    descriptor = {
        "release_type": "composite_serving_release", "schema_version": RELEASE_SCHEMA_V2,
        "release_id": release_id, "snapshot_id": snapshot_id, "snapshot_manifest_sha256": manifest_sha,
        "database_generation_id": generation, "read_model_release_id": None, "read_model_manifest_sha256": None, "read_model_release_content_hash": None,
        "source_contract_id": manifest["source_contract_id"], "source_contract_version": manifest["source_contract_version"],
        "component_bindings": [
            {"component_id": "CN_PUBLIC_FUND", "snapshot_id": snapshot_id, "manifest_sha256": manifest_sha, "database_generation_id": generation, "integration_proof": component_proof},
            {"component_id": "CN_A_SHARE", "snapshot_id": snapshot_id, "manifest_sha256": manifest_sha, "database_generation_id": generation, "integration_proof": component_proof},
        ],
        "serving_contracts": [
            {"contract_id": "china_public_fund_minimum_query_v1", "owner": "embedded_release_contract", "contract": fund_contract, "content_sha256": contract_content_hash(fund_contract), "source_snapshot_contract": {"relative_path": FUND_QUERY_CONTRACT, "content_sha256": sha256_file(root / FUND_QUERY_CONTRACT)}},
            {"contract_id": "china_equity_minimum_daily_query_v1", "owner": "embedded_release_contract", "contract": equity_contract, "content_sha256": contract_content_hash(equity_contract)},
        ],
    }
    descriptor["release_content_hash"] = release_content_hash(descriptor)
    verify_release_descriptor(descriptor, snapshot_root=paths.snapshot)
    registry_path = paths.release_registry_root / "unpublished" / f"{release_id}.json"
    if registry_path.exists() and json.loads(registry_path.read_text(encoding="utf-8")) != descriptor:
        raise FirstInstallBootstrapError("release registry identity already names different content")
    write_json_atomic(registry_path, descriptor)
    control = root / CONTROL_RELATIVE
    control_member = next(row for row in manifest["files"] if row["relative_path"] == CONTROL_RELATIVE)
    retention_binding = {"schema_version": SERVING_BINDING_SCHEMA, "release_descriptor": descriptor, "database_version_id": snapshot_id, "manifest_sha256": manifest_sha, "control_dependency": {"owner": "snapshot_member", "relative_path": CONTROL_RELATIVE, "content_sha256": control_member["content_sha256"], "byte_count": control_member["byte_count"]}, "read_model_dependency": None}
    consumer_id, closure = register_retained_consumer(paths.control_database, retention_binding, consumer_type="serving_release", snapshot_root=paths.snapshot, control_relative_path=CONTROL_RELATIVE, required_member_paths=[])
    transition = transition_active_release(active_pointer=paths.active_pointer, control_database=paths.control_database, target_release=descriptor, target_retention_consumer_id=consumer_id, expected_active_sha256="", operation_id=publication_operation_id or f"initial_publication:{release_id}", operation_type="publication", committed_at_utc=committed_at_utc, snapshot_root=paths.snapshot, failure_point=failure_point, allow_initial_publication=True)
    return {"release": descriptor, "retention_consumer_id": consumer_id, "retention_closure": closure, "transition": transition}
