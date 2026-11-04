"""User-safe, release-bound logical Data catalog and field dictionary.

The manifest proves presence, not financial row counts or query availability.
Physical members and internal control tables never become product datasets.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from backend.app.core.artifact_io import canonical_json, sha256_file
from backend.app.core.data_product_lifecycle import LifecycleEvidenceError, release_lifecycle_evidence
from backend.app.core.serving_release import PinnedServingRelease, pin_serving_release
from backend.app.core.storage_profile import resolve_unpublished_snapshot_path


CATALOG_CONTRACT = "fr_release_bound_data_catalog_v1"
ROOT = Path(__file__).resolve().parents[3]
METRICS_PATH = ROOT / "config" / "metrics_registry.json"
DAILY_DATASETS = {
    "fund.share_class_daily": ("Fund", "fund_share_class", {"fund.nav", "fund.accumulated_nav"}),
    "fund.listing_daily": ("Fund", "listing", {"market.close_price", "market.volume", "market.trade_amount"}),
    "equity.daily_market": ("Equity", "listing", {
        "equity.open", "equity.high", "equity.low", "equity.close", "market.volume",
        "market.trade_amount", "market.turnover_rate",
    }),
}

DOMAIN_DESCRIPTIONS = {
    "financial_statements": ("governed_facts.financial_statements", "Financial statement facts", "financial reporting entity and declared report period/version"),
    "fixed_income": ("governed_facts.fixed_income", "Fixed Income facts", "accepted security/Series and economic time/version"),
    "indices_derivatives": ("governed_facts.index_and_derivative", "Index/Derivative governed facts", "mixed legacy domain; inspect before exposing rows"),
    "macro_fx_rates": ("governed_facts.macro_and_fx", "Macro/FX governed facts", "mixed legacy domain; inspect before exposing rows"),
}


def _field(name: str, display: str, definition: str, *, kind: str = "string", nullable: bool = False,
           visibility: str = "explorer", identity_role: str | None = None,
           time_role: str | None = None, enumeration: Mapping[str, str] | None = None,
           origin: str | None = None) -> dict[str, Any]:
    return {
        "name": name, "display_name": display, "definition": definition,
        "data_type": kind, "nullable": nullable, "format": "ISO-8601 date" if time_role else None,
        "unit_semantics": None, "currency_semantics": None,
        "time_role": time_role, "identity_role": identity_role,
        "value_class": "source" if name == "source" else "direct",
        "example": None, "enum_values": dict(enumeration or {}),
        "origin": origin or "selected release owner", "join_cardinality": "one_to_one",
        "derivation": None, "visibility": visibility,
    }


IDENTITY_FIELDS = (
    _field("object_id", "FR object ID", "Durable identity of the selected financial object.", identity_role="durable_object_id"),
    _field("display_name", "Name", "Accepted display name in the fixed release.", visibility="ordinary"),
    _field("lifecycle_class", "Lifecycle", "Release-bound state of this accepted financial object; independent of exact start/end precision.",
           enumeration={"Current": "authoritatively effective", "Historical": "conclusively ended", "Unconfirmed": "not authoritatively classified"}),
    _field("lifecycle_classification_status", "Lifecycle evidence", "Explains the accepted evidence role or unresolved reason for this object's class.", visibility="explorer"),
)
FUND_IDENTITY_FIELDS = IDENTITY_FIELDS + (
    _field("subject_type", "Fund object type", "Product, share class, or listing identity."),
    _field("jurisdiction", "Jurisdiction", "Jurisdiction recorded by the accepted Fund owner.", nullable=True),
    _field("effective_start", "Recorded effective start", "Owner-recorded boundary; not a lifecycle classification reference.", kind="date", nullable=True, time_role="recorded_effective_start"),
    _field("effective_end", "Recorded effective end", "Owner-recorded boundary; null does not mean Current.", kind="date", nullable=True, time_role="recorded_effective_end"),
)
ESTIMATED_DELISTING_FIELD = _field(
    "estimated_delisting_date", "Announced delisting date",
    "Officially evidenced future listing-termination date; null after effective termination or when unproved.",
    kind="date", nullable=True, time_role="scheduled_listing_end",
)
FUND_LISTING_FIELDS = FUND_IDENTITY_FIELDS + (ESTIMATED_DELISTING_FIELD,)
EQUITY_LISTING_FIELDS = IDENTITY_FIELDS + (
    _field("subject_type", "Object type", "Accepted listing episode identity."),
    _field("external_code", "Listing code", "Exchange-scoped code; not an economic identity by itself."),
    _field("exchange", "Venue", "Listing venue (SSE, SZSE, BSE, or HKEX)."),
    _field("market_jurisdiction", "Market jurisdiction", "Market-jurisdiction dimension, separate from venue and Universe."),
    _field("listing_start_date", "Listing start", "Exact date only where proved by accepted evidence.", kind="date", nullable=True, time_role="listing_start"),
    _field("listing_start_boundary", "Start-date confidence", "Exact, bounded, or unknown accepted start boundary.", nullable=True),
    _field("listing_end_date", "Listing end", "Owner-recorded end boundary; null does not mean Current.", kind="date", nullable=True, time_role="listing_end"),
    ESTIMATED_DELISTING_FIELD,
)
ALIAS_FIELDS = (
    _field("object_id", "FR object ID", "Accepted alias target identity.", identity_role="durable_object_id"),
    _field("subject_type", "Object type", "Alias target financial object type."),
    _field("alias_kind", "Identifier type", "Accepted scoped code or name alias."),
    _field("alias_value", "Identifier", "Accepted scoped code or name value."),
    _field("effective_start", "Alias effective start", "Start of the accepted alias interval.", kind="date", nullable=True, time_role="alias_effective_start"),
    _field("effective_end", "Alias effective end", "End of the accepted alias interval.", kind="date", nullable=True, time_role="alias_effective_end"),
)
DATA_FIELDS = (
    _field("subject_id", "Selected object", "Durable share-class or listing identity.", identity_role="durable_object_id", visibility="ordinary"),
    _field("economic_time", "Observation date", "Date of a returned observation; no date is filled or invented.",
           kind="date", time_role="observation_date", visibility="ordinary"),
    _field("provenance", "Source", "Readable source institution and class when established by the returned point; otherwise explicitly not projected.",
           kind="object", nullable=True, visibility="ordinary", origin="source family carried by selected standard fact"),
    _field("support_trace", "Source audit reference", "Raw source observation identity for support and reproducibility, not an ordinary provider label.",
           kind="object", nullable=True, visibility="support", origin="accepted standard fact lineage"),
)


def _dataset(dataset_id: str, display: str, description: str, grain: str, *, universe: str | None,
             preview: bool, export: bool, classification_as_of: str | None = None,
             fields: tuple[dict[str, Any], ...] = (), relationships: tuple[dict[str, str], ...] = (),
             lifecycle: str = "object_lifecycle_where_supported", export_kind: str = "daily") -> dict[str, Any]:
    scopes = (["current_preview", "all_matching_filters", "complete_logical_dataset"]
              if export and export_kind == "identity" else
              ["current_preview", "all_matching_bounded_interval", "all_matching_selected_interval_local_job"]
              if export else [])
    return {
        "dataset_id": dataset_id, "display_name": display, "description": description,
        "universe": universe, "row_grain": grain,
        "relationships": list(relationships), "lifecycle_applicability": lifecycle,
        "classification_as_of": classification_as_of,
        "visibility": "explorer", "presence": "present",
        "preview": "available" if preview else "present_not_exposed",
        "filter": "available" if preview else "present_not_exposed",
        "export": "available" if export else "present_not_exposed",
        "export_scopes": scopes,
        "entire_dataset_export": "local_job_available" if export and export_kind == "identity" else "not_exposed",
        "lifecycle_filter_status": "not_applicable",
        "geographic_coverage": ("Mainland China Public Fund" if universe == "Fund" else
                                "Mainland China and Hong Kong accepted Equity" if universe == "Equity" else None),
        "logical_row_count": None, "logical_row_count_status": "not_computed",
        "fields": list(fields),
    }


def _metric_field(metric_id: str, registry: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    metric = registry.get(metric_id)
    if metric is None:
        raise ValueError(f"supported metric has no canonical metric definition: {metric_id}")
    date_contract = metric.get("date_time_contract") or {}
    result = _field(metric_id, str(metric.get("english_name") or metric_id),
                    str(metric.get("financial_definition") or ""), kind=str(metric.get("value_type") or "number"),
                    nullable=True, visibility="ordinary", time_role=str(date_contract.get("primary_role") or "observation_date"),
                    origin="accepted standard fact for selected Series")
    result["unit_semantics"] = metric.get("canonical_unit")
    result["currency_semantics"] = metric.get("currency_rule")
    result["value_class"] = "derived" if str(metric.get("direct_derived_preference") or "").startswith("derived") else "standard_fact"
    result["derivation"] = metric.get("financial_definition") if result["value_class"] == "derived" else None
    return result


def release_catalog(release: PinnedServingRelease | None = None) -> dict[str, Any]:
    bound = release or pin_serving_release()
    if not bound.snapshot_id or not bound.release_id:
        raise ValueError("a published composite release is required")
    root = resolve_unpublished_snapshot_path(bound.snapshot_id)
    manifest = json.loads((root / "metadata/corrected_candidate_manifest_v1.json").read_text(encoding="utf-8"))
    members = {str(row["relative_path"]) for row in manifest.get("files", [])}
    registry = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    metrics = {str(row["metric_id"]): row for row in registry["metrics"]}
    fund_cutoff = None
    equity_cutoff = None
    fund_state = root / "metadata/china_public_fund/validated_update_state_v1.json"
    equity_state = root / "metadata/a_share_update/validated_update_state_v1.json"
    if fund_state.is_file() and "metadata/china_public_fund/validated_update_state_v1.json" in members:
        fund_cutoff = json.loads(fund_state.read_text(encoding="utf-8")).get("authoritative_cutoff")
    if equity_state.is_file() and "metadata/a_share_update/validated_update_state_v1.json" in members:
        equity_cutoff = json.loads(equity_state.read_text(encoding="utf-8")).get("authoritative_cutoff")

    # These are source-observation cutoffs, not a proved combined lifecycle
    # classification date.  Do not present them as `classification_as_of`.
    source_cutoffs = {"Fund": fund_cutoff, "Equity": equity_cutoff}
    fund_cutoff = None
    equity_cutoff = None
    try:
        release_lifecycle_evidence(bound)
        lifecycle_ready = True
    except LifecycleEvidenceError:
        lifecycle_ready = False
    datasets: list[dict[str, Any]] = []
    if "metadata/china_public_fund/fr_china_public_fund_control_v1.sqlite" in members:
        datasets.extend([
            _dataset("fund.products", "Fund products", "Accepted public-fund products; identity is distinct from share class.",
                     "one Fund product identity", universe="Fund", preview=True, export=True,
                     classification_as_of=fund_cutoff, fields=FUND_IDENTITY_FIELDS, export_kind="identity"),
            _dataset("fund.share_classes", "Fund share classes", "Accepted share-class identities and their product relationship.",
                     "one Fund share-class identity", universe="Fund", preview=True, export=True,
                     classification_as_of=fund_cutoff, fields=FUND_IDENTITY_FIELDS,
                     relationships=({"target": "fund.products", "cardinality": "many_to_one", "role": "share_class_of_product"},),
                     export_kind="identity"),
            _dataset("fund.listings", "Fund listings", "Accepted exchange-listing identities, separate from product and share class.",
                     "one Fund listing episode", universe="Fund", preview=True, export=True,
                     classification_as_of=fund_cutoff, fields=FUND_LISTING_FIELDS, export_kind="identity"),
            _dataset("fund.identifier_history", "Fund identifier history", "Accepted scoped code/name aliases; multiple aliases may refer to one identity.",
                     "one accepted alias interval", universe="Fund", preview=True, export=True,
                     classification_as_of=fund_cutoff, lifecycle="alias_interval_not_object_lifecycle",
                     fields=ALIAS_FIELDS,
                     export_kind="identity"),
        ])
    if "metadata/a_share_update/authoritative_identity_reconciliation_v1.json" in members:
        datasets.extend([
            _dataset("equity.listings", "Equity listings", "Accepted economic listing episodes across Mainland China and Hong Kong.",
                     "one accepted listing episode", universe="Equity", preview=True, export=True,
                     classification_as_of=equity_cutoff, fields=EQUITY_LISTING_FIELDS,
                     export_kind="identity"),
            _dataset("equity.identifier_history", "Equity identifier history", "Accepted episode-scoped code and name aliases.",
                     "one accepted alias interval", universe="Equity", preview=True, export=True,
                     classification_as_of=equity_cutoff, lifecycle="alias_interval_not_object_lifecycle",
                     fields=ALIAS_FIELDS + (_field("exchange", "Venue", "Alias target listing venue."),),
                     export_kind="identity"),
        ])
    domains = {
        path.split("/", 2)[1].removeprefix("domain=")
        for path in members if path.startswith("standard_facts/domain=")
    }
    if "funds_etfs" in domains:
        datasets.extend([
            _dataset("fund.share_class_daily", "Fund share-class daily values", "NAV and accumulated NAV of a selected accepted share class.",
                     "one selected share class × returned observation date; metrics are separate cells", universe="Fund", preview=True, export=True,
            classification_as_of=fund_cutoff, fields=DATA_FIELDS + tuple(_metric_field(m, metrics) for m in ("fund.nav", "fund.accumulated_nav"))),
            _dataset("fund.listing_daily", "Listed Fund market data", "Available market values of a selected accepted Fund listing.",
                     "one selected listing × returned observation date; metrics are separate cells", universe="Fund", preview=True, export=True,
                     classification_as_of=fund_cutoff, fields=DATA_FIELDS + tuple(_metric_field(m, metrics) for m in ("market.close_price", "market.volume", "market.trade_amount"))),
        ])
    if "equity" in domains:
        from backend.app.core.china_equity_query import METRIC_SERIES_FAMILY
        datasets.append(_dataset(
            "equity.daily_market", "Equity daily market data", "Unadjusted daily values for an accepted listing episode; unsupported fields remain unavailable.",
            "one selected listing episode × returned observation date; metrics are separate cells", universe="Equity", preview=True, export=True,
            classification_as_of=equity_cutoff,
            fields=DATA_FIELDS + tuple(_metric_field(m, metrics) for m in METRIC_SERIES_FAMILY),
        ))
    for physical_domain in sorted(domains - {"funds_etfs", "equity"}):
        unknown_id = "governed_facts.unmapped_" + hashlib.sha256(physical_domain.encode()).hexdigest()[:10]
        logical_id, display, grain = DOMAIN_DESCRIPTIONS.get(
            physical_domain, (unknown_id, "Unmapped governed facts", "declared fact grain not exposed"))
        datasets.append(_dataset(
            logical_id, display,
            "Standard facts are present in this release, but no user-safe preview/export contract has been accepted.",
            grain, universe=None, preview=False, export=False,
            lifecycle="not_projected", fields=(),
        ))
    for dataset in datasets:
        if dataset["dataset_id"] in {"fund.products", "fund.share_classes", "fund.listings", "equity.listings"}:
            dataset["lifecycle_filter_status"] = (
                "available_for_accepted_identities" if lifecycle_ready else "unavailable_for_this_release"
            )
            dataset["ordinary_default_lifecycle"] = "Current"
    binding = {"release_id": bound.release_id, "release_hash": bound.release_hash,
               "snapshot_id": bound.snapshot_id, "database_generation_id": bound.database_generation_id}
    version_material = {"binding": binding, "contract": CATALOG_CONTRACT,
                        "metric_registry_sha256": sha256_file(METRICS_PATH),
                        "datasets": datasets}
    version = hashlib.sha256(canonical_json(version_material).encode("utf-8")).hexdigest()
    return {
        "schema_version": CATALOG_CONTRACT, "catalog_version": version, "binding": binding,
        "classification_references": {"Fund": fund_cutoff, "Equity": equity_cutoff},
        "source_cutoffs_not_lifecycle_references": source_cutoffs,
        "classification_reference_note": "no global classification-as-of date; immutable accepted owner evidence determines each lifecycle state",
        "datasets": datasets,
        "scope_note": "present governed logical families only; presence does not prove external population completeness or query coverage",
    }


def data_dictionary(dataset_id: str, *, release: PinnedServingRelease | None = None) -> dict[str, Any]:
    catalog = release_catalog(release)
    dataset = next((row for row in catalog["datasets"] if row["dataset_id"] == dataset_id), None)
    if dataset is None:
        raise KeyError(dataset_id)
    return {
        "schema_version": "fr_data_dictionary_v1",
        "catalog_version": catalog["catalog_version"], "binding": catalog["binding"],
        "dataset_id": dataset_id, "row_grain": dataset["row_grain"],
        "fields": dataset["fields"], "visibility_classes": ["ordinary", "explorer", "support", "backend_only"],
        "field_scope": "only fields in the currently exposed logical product contract",
    }
