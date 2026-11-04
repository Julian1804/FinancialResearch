"""Release-bound, cardinality-safe ordinary Fund and Equity data tables.

This is a presentation projection over the two financial query owners.  It
does not create facts, infer identity, or reinterpret their data states.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Sequence

from backend.app.core.china_equity_query import (
    METRIC_SERIES_FAMILY,
    ChinaEquityQueryError,
    ChinaEquityQueryService,
)
from backend.app.core.china_public_fund_query import (
    SUPPORTED_METRICS,
    ChinaPublicFundQueryService,
    FundQueryError,
)
from backend.app.core.serving_release import PinnedServingRelease, pin_serving_release


class DataProductError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


SOURCE_LABELS = {
    "CSRC_EID": ("CSRC electronic fund disclosure", "official regulatory disclosure"),
    "Tencent": ("Tencent public market data", "public provider"),
    "SSE": ("Shanghai Stock Exchange", "official exchange"),
    "SZSE": ("Shenzhen Stock Exchange", "official exchange"),
}


def _provenance(point: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    source = point.get("source") or {}
    family = source.get("source_family")
    label = SOURCE_LABELS.get(str(family)) if family else None
    ordinary = {
        "status": "identified" if label else "unavailable_not_proven",
        "source_name": label[0] if label else None,
        "source_class": label[1] if label else None,
        "unavailable_reason": None if label else "source attribution is not proved by this release-bound point",
        "observation_date_role": "economic_observation_date",
    }
    support = {"source_observation_id": source.get("source_observation_id") or point.get("source_observation_id")}
    return ordinary, support


def _interval(start: str, end: str, *, equity: bool) -> None:
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError as exc:
        raise DataProductError("invalid_date_range", "start/end must be ISO dates") from exc
    if first > last or (equity and (last - first).days > 366):
        raise DataProductError("invalid_date_range", "interval exceeds the selected owner's bounded contract")


def _binding(release: PinnedServingRelease) -> dict[str, Any]:
    return {
        "release_id": release.release_id,
        "release_hash": release.release_hash,
        "snapshot_id": release.snapshot_id,
        "database_generation_id": release.database_generation_id,
    }


def research_table(
    *, universe: str, subject_id: str, metric_ids: Sequence[str], start: str,
    end: str, max_rows: int = 5_000, subject_type: str | None = None,
    release: PinnedServingRelease | None = None,
    fund_service: ChinaPublicFundQueryService | None = None,
    equity_service: ChinaEquityQueryService | None = None,
) -> dict[str, Any]:
    """Union *returned* dates, never aliases/provenance rows or inferred dates.

    A failed field is recorded separately from a successful field with no
    observation.  One metric is one selected Series in the current owner
    contracts; duplicate dates fail that field instead of choosing a row.
    """
    if universe not in {"Fund", "Equity"}:
        raise DataProductError("unsupported_universe", "only Fund and Equity are supported")
    if not subject_id or len(subject_id) > 200:
        raise DataProductError("invalid_subject", "a selected durable subject is required")
    if not metric_ids or len(metric_ids) > 8 or len(set(metric_ids)) != len(metric_ids):
        raise DataProductError("invalid_fields", "select between one and eight distinct fields")
    if not 1 <= max_rows <= 5_000:
        raise DataProductError("invalid_row_limit", "max_rows must be between 1 and 5000")
    equity = universe == "Equity"
    _interval(start, end, equity=equity)
    if equity:
        if subject_type not in (None, "listing"):
            raise DataProductError("invalid_subject_type", "Equity data requires a listing episode")
        unsupported = set(metric_ids) - set(METRIC_SERIES_FAMILY)
        subject_type = "listing"
    else:
        if subject_type not in {"fund_share_class", "listing"}:
            raise DataProductError("invalid_subject_type", "select a Fund share class or listed form")
        unsupported = {metric for metric in metric_ids if SUPPORTED_METRICS.get(metric) != subject_type}
    if unsupported:
        raise DataProductError("unsupported_fields", "one or more fields do not belong to the selected financial object")

    bound = release or pin_serving_release()
    if equity:
        owner = equity_service or ChinaEquityQueryService.for_release(bound)
    else:
        owner = fund_service or ChinaPublicFundQueryService.for_binding(
            access_mode="release", snapshot_id=bound.snapshot_id,
            manifest_sha256=str(bound.component("CN_PUBLIC_FUND")["manifest_sha256"]),
            release=bound,
        )
    observations: dict[str, dict[str, dict[str, Any]]] = {}
    fields: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    all_dates: set[str] = set()
    for metric_id in metric_ids:
        try:
            if equity:
                result = owner.time_series(
                    listing_id=subject_id, metric_id=metric_id,
                    adjustment_basis="unadjusted", start=start, end=end,
                    max_rows=max_rows,
                )
                points = result["points"]
                availability = result["status"]
            else:
                result = owner.time_series(
                    subject_type=str(subject_type), subject_id=subject_id,
                    metric_id=metric_id, start=start, end=end,
                    max_rows=max_rows,
                )
                points = result["points"]
                availability = result["data_state"]
            series = result.get("series") or {}
            by_date: dict[str, dict[str, Any]] = {}
            for point in points:
                observation_date = str(point["economic_time"])
                if observation_date in by_date:
                    raise DataProductError("ambiguous_daily_grain", "multiple observations occupy one selected field/date", 409)
                ordinary_provenance, support_trace = _provenance(point)
                by_date[observation_date] = {
                    "value": point["value"], "unit": point.get("unit"),
                    "currency": point.get("currency"), "scale": point.get("scale"),
                    "time_role": point.get("time_role"),
                    "provenance": ordinary_provenance,
                    "support_trace": support_trace,
                }
            observations[metric_id] = by_date
            all_dates.update(by_date)
            fields.append({
                "metric_id": metric_id, "series_id": series.get("series_id"),
                "availability": availability, "returned_observation_count": len(by_date),
                "retrieval": "complete", "adjustment_basis": "unadjusted" if equity else None,
            })
        except (FundQueryError, ChinaEquityQueryError, DataProductError) as exc:
            code = str(getattr(exc, "code", type(exc).__name__))
            failures.append({"metric_id": metric_id, "code": code, "retrieval": "failed"})
            fields.append({"metric_id": metric_id, "availability": "unknown", "retrieval": "failed"})
    ordered_dates = sorted(all_dates)
    if len(ordered_dates) > max_rows:
        raise DataProductError("result_too_large", "table union exceeds max_rows", 413)
    return {
        "schema_version": "fr_data_product_research_table_v1",
        "binding": _binding(bound), "universe": universe,
        "subject": {"type": subject_type, "id": subject_id},
        "row_grain": "one_selected_subject_x_one_returned_observation_date",
        "interval": {"start": start, "end": end},
        "status": "partial_failure" if failures else "complete",
        "fields": fields, "field_failures": failures,
        "row_count": len(ordered_dates),
        "rows": [
            {"economic_time": day, "cells": {
                metric: observations.get(metric, {}).get(day) for metric in metric_ids
            }} for day in ordered_dates
        ],
        "missing_cell_semantics": "no_returned_observation_only_when_field_retrieval_complete",
        "failed_field_semantics": "all cells for a failed field are unknown_not_blank",
        "fill_policy": "none",
    }
