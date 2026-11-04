"""Release-bound logical identity rows for the Data Explorer.

These are application projections of accepted Fund/Equity owners, not a new
identity registry. Lifecycle is read from evidence bound to the fixed release.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from backend.app.core.china_equity_query import ChinaEquityQueryService
from backend.app.core.china_public_fund_query import ChinaPublicFundQueryService
from backend.app.core.data_product_lifecycle import (
    LifecycleEvidenceError, fund_lifecycle, release_lifecycle_evidence,
)
from backend.app.core.data_product_research_table import DataProductError
from backend.app.core.serving_release import PinnedServingRelease


FUND_TYPES = {
    "fund.products": "fund",
    "fund.share_classes": "fund_share_class",
    "fund.listings": "listing",
}
IDENTITY_DATASETS = set(FUND_TYPES) | {
    "fund.identifier_history", "equity.listings", "equity.identifier_history",
}


def validate_identity_filters(
    dataset_id: str, *, market: str, exchange: str | None,
    lifecycle: str | None, subject_id: str | None, query: str | None,
) -> None:
    if dataset_id not in IDENTITY_DATASETS:
        raise DataProductError("logical_dataset_not_exposed", "dataset has no accepted identity row contract", 409)
    if lifecycle not in {None, "All", "Current", "Historical", "Unconfirmed"}:
        raise DataProductError("invalid_identity_filter", "unsupported lifecycle filter")
    if dataset_id.endswith("identifier_history") and lifecycle not in {None, "All"}:
        raise DataProductError("lifecycle_not_applicable", "identifier intervals are not object lifecycle", 409)
    if market not in {"All", "Mainland", "Hong Kong"} or exchange not in {None, "SSE", "SZSE", "BSE", "HKEX"}:
        raise DataProductError("invalid_identity_filter", "unsupported market or venue filter")
    if query is not None and len(query) > 100 or subject_id is not None and len(subject_id) > 200:
        raise DataProductError("invalid_identity_filter", "identity filter exceeds bounded length")
    if dataset_id.startswith("fund."):
        if market == "Hong Kong" or exchange == "HKEX":
            raise DataProductError("unsupported_market_scope", "Hong Kong Fund identity is not bound in this release", 409)
        if exchange:
            raise DataProductError("venue_filter_unavailable", "Fund venue filter is not proved for this logical dataset", 409)
    elif (market == "Mainland" and exchange == "HKEX") or (
        market == "Hong Kong" and exchange in {"SSE", "SZSE", "BSE"}
    ):
        raise DataProductError("contradictory_market_filter", "market and venue filters disagree")


def effective_identity_lifecycle(
    dataset_id: str, lifecycle: str | None, *, subject_id: str | None, query: str | None,
) -> str:
    if lifecycle is not None:
        return lifecycle
    # Browsing defaults to Current. Exact object selection and code/name search
    # must not erase accepted Historical or Unconfirmed objects.
    if dataset_id.endswith("identifier_history") or subject_id or query:
        return "All"
    return "Current"


def _fund_owner(release: PinnedServingRelease) -> ChinaPublicFundQueryService:
    return ChinaPublicFundQueryService.for_binding(
        access_mode="release", snapshot_id=release.snapshot_id,
        manifest_sha256=str(release.component("CN_PUBLIC_FUND")["manifest_sha256"]),
        release=release,
    )


def _equity_rows(dataset_id: str, release: PinnedServingRelease) -> list[dict[str, Any]]:
    listings = ChinaEquityQueryService.for_release(release).accepted_listing_rows()
    if dataset_id == "equity.listings":
        return [
            {"object_id": row["listing_id"], "subject_type": "listing",
             "display_name": row["display_name"], "external_code": row["external_code"],
             "exchange": row["exchange"], "market_jurisdiction": row["market_jurisdiction"],
             "listing_start_date": row["listing_start_date"],
             "listing_start_boundary": row["listing_start_boundary"],
             "listing_end_date": row["listing_end_date"],
             "estimated_delisting_date": row["estimated_delisting_date"],
             "lifecycle_class": row["lifecycle_class"],
             "lifecycle_classification_status": row["lifecycle_classification_status"]}
            for row in listings
        ]
    result = {}
    for listing in listings:
        for kind, entries, value_key in (
            ("code", listing["code_aliases"], "code"),
            ("name", listing["name_aliases"], "value"),
        ):
            for alias in entries:
                value = alias.get(value_key)
                if not value:
                    continue
                row = {"object_id": listing["listing_id"], "subject_type": "listing",
                       "exchange": listing["exchange"], "alias_kind": kind,
                       "alias_value": str(value),
                       "effective_start": alias.get("effective_from"),
                       "effective_end": alias.get("effective_to")}
                key = (row["object_id"], kind, row["alias_value"],
                       row["effective_start"], row["effective_end"])
                result[key] = row
    return list(result.values())


def _fund_rows(dataset_id: str, release: PinnedServingRelease) -> list[dict[str, Any]]:
    view = _fund_owner(release)._control_view()
    if dataset_id in FUND_TYPES:
        kind = FUND_TYPES[dataset_id]
        try:
            evidence = release_lifecycle_evidence(release)
        except LifecycleEvidenceError:
            evidence = None  # historical release: All remains inspectable
        result = []
        accepted = [row for row in view.subjects(kind)
                    if row.get("domain") == "funds_etfs"
                    and str(row.get("resolution_status") or "").startswith("accepted_")]
        if kind == "fund" and evidence:
            missing = evidence.historical_fund_subjects - {str(row["subject_id"]) for row in accepted}
            if missing:
                raise DataProductError(
                    "historical_product_identity_unmatched",
                    "pinned historical Product assignments do not match accepted Product subjects", 409,
                )
        for row in accepted:
            attrs = json.loads(row.get("attributes_json") or "{}")
            projected = (fund_lifecycle(row, kind=kind, evidence=evidence) if evidence else {
                "effective_end": row.get("effective_end"), "lifecycle_class": None,
                "lifecycle_classification_status": "unavailable_for_this_release",
                "estimated_delisting_date": None,
            })
            item = {
                "object_id": row["subject_id"], "subject_type": kind,
                "display_name": attrs.get("display_name"),
                "jurisdiction": attrs.get("jurisdiction") or row.get("market"),
                "effective_start": row.get("effective_start"),
                "effective_end": projected["effective_end"],
                "lifecycle_class": projected["lifecycle_class"],
                "lifecycle_classification_status": projected["lifecycle_classification_status"],
            }
            if kind == "listing":
                item["estimated_delisting_date"] = projected["estimated_delisting_date"]
            result.append(item)
        return result
    accepted_targets = {
        (kind, row["subject_id"])
        for kind in FUND_TYPES.values()
        for row in view.subjects(kind)
        if row.get("domain") == "funds_etfs"
        and str(row.get("resolution_status") or "").startswith("accepted_")
    }
    try:
        evidence = release_lifecycle_evidence(release)
    except LifecycleEvidenceError:
        evidence = None
    return [
        {"object_id": row["subject_id"], "subject_type": row["subject_type"],
         "alias_kind": row["alias_type"], "alias_value": row["alias_value"],
         "effective_start": row["effective_start"],
         "effective_end": (None if evidence and row["subject_id"] in evidence.unproved_fund_listing_ends
                           and row["subject_type"] == "listing" else row["effective_end"])}
        for row in view.aliases_matching(" WHERE acceptance_status='accepted'", ())
        if (row.get("subject_type"), row.get("subject_id")) in accepted_targets
    ]


def identity_dataset_rows(
    dataset_id: str, *, release: PinnedServingRelease,
    market: str = "All", exchange: str | None = None,
    lifecycle: str | None = None, subject_id: str | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """Return exact logical rows after server-side filters, never physical counts."""
    lifecycle = effective_identity_lifecycle(dataset_id, lifecycle, subject_id=subject_id, query=query)
    validate_identity_filters(dataset_id, market=market, exchange=exchange,
                              lifecycle=lifecycle, subject_id=subject_id, query=query)
    if lifecycle != "All":
        try:
            release_lifecycle_evidence(release)
        except LifecycleEvidenceError as exc:
            raise DataProductError("lifecycle_evidence_unavailable", str(exc), 409) from exc
    if dataset_id.startswith("fund."):
        rows = _fund_rows(dataset_id, release)
    else:
        rows = _equity_rows(dataset_id, release)
        venues = ({"SSE", "SZSE", "BSE"} if market == "Mainland" else
                  {"HKEX"} if market == "Hong Kong" else None)
        rows = [row for row in rows
                if (venues is None or row.get("exchange") in venues)
                and (exchange is None or row.get("exchange") == exchange)]
    if subject_id is not None:
        rows = [row for row in rows if row["object_id"] == subject_id]
    alias_matches: set[str] = set()
    if query and dataset_id in FUND_TYPES:
        needle = " ".join(query.casefold().split())
        alias_matches = {
            row["subject_id"] for row in _fund_owner(release)._control_view().aliases_matching(
                " WHERE acceptance_status='accepted'", ())
            if row.get("subject_type") == FUND_TYPES[dataset_id]
            and needle in str(row.get("alias_value") or "").casefold()
        }
    if query:
        needle = " ".join(query.casefold().split())
        rows = [row for row in rows if row["object_id"] in alias_matches or needle in " ".join(
            str(row.get(key) or "") for key in ("display_name", "external_code", "alias_value")
        ).casefold()]
    if lifecycle != "All":
        rows = [row for row in rows if row.get("lifecycle_class") == lifecycle]
    return sorted(rows, key=lambda row: (
        str(row.get("exchange") or ""), str(row.get("subject_type") or ""),
        str(row["object_id"]), str(row.get("alias_kind") or ""),
        str(row.get("alias_value") or ""), str(row.get("effective_start") or ""),
    ))
