"""Transport for release-bound Data product projections."""

from __future__ import annotations

import csv
import base64
import binascii
import hashlib
import io
import json
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from backend.app.core.china_equity_query import ChinaEquityQueryError, ChinaEquityQueryService
from backend.app.core.china_public_fund_query import ChinaPublicFundQueryService, FundQueryError
from backend.app.core.data_product_catalog import DAILY_DATASETS, data_dictionary, release_catalog
from backend.app.core.data_product_identity import effective_identity_lifecycle, identity_dataset_rows
from backend.app.core.data_product_lifecycle import (
    LifecycleEvidenceError, fund_lifecycle, release_lifecycle_evidence,
)
from backend.app.core.data_product_export_jobs import (
    IDENTITY_FIELDS, cancel_job, completed_output, create_daily_job, create_identity_job, job_status,
    run_daily_job, run_identity_job, sweep_expired,
)
from backend.app.core.data_product_research_table import DataProductError, research_table
from backend.app.core.serving_release import (
    PinnedServingRelease, ServingReleaseError, pin_registered_serving_release,
    pin_serving_release,
)


router = APIRouter(prefix="/api/data-product", tags=["release-bound-data-product"])


class ResearchTableRequest(BaseModel):
    universe: Literal["Fund", "Equity"]
    subject_type: str | None = None
    subject_id: str
    metric_ids: list[str] = Field(min_length=1, max_length=8)
    start: str
    end: str
    max_rows: int = Field(default=5_000, ge=1, le=5_000)
    release_id: str | None = None
    release_hash: str | None = None


class IdentityReadRequest(BaseModel):
    market: Literal["All", "Mainland", "Hong Kong"] = "All"
    exchange: str | None = None
    lifecycle: Literal["All", "Current", "Historical", "Unconfirmed"] | None = None
    subject_id: str | None = None
    query: str | None = None
    release_id: str | None = None
    release_hash: str | None = None


class IdentityExportRequest(IdentityReadRequest):
    scope: Literal["all_matching_filters", "complete_logical_dataset"] = "all_matching_filters"
    fields: list[str] | None = None


def _release(release_id: str | None, release_hash: str | None) -> PinnedServingRelease:
    if bool(release_id) != bool(release_hash):
        raise HTTPException(status_code=400, detail={"code": "explicit_release_binding_required"})
    try:
        return (pin_registered_serving_release(release_id, release_hash)
                if release_id and release_hash else pin_serving_release())
    except ServingReleaseError as exc:
        raise HTTPException(status_code=409, detail={"code": "release_binding_unavailable"}) from exc


@router.get("/catalog")
def catalog(release_id: str | None = None, release_hash: str | None = None) -> dict[str, Any]:
    return release_catalog(_release(release_id, release_hash))


@router.get("/dictionary/{dataset_id}")
def dictionary(dataset_id: str, release_id: str | None = None, release_hash: str | None = None) -> dict[str, Any]:
    try:
        return data_dictionary(dataset_id, release=_release(release_id, release_hash))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "logical_dataset_not_found"}) from exc


@router.post("/identity-preview/{dataset_id}")
def identity_preview(
    dataset_id: str, request: IdentityReadRequest,
    limit: int = Query(default=100, ge=1, le=500), cursor: str | None = Query(default=None, max_length=512),
) -> dict[str, Any]:
    bound = _release(request.release_id, request.release_hash)
    filters = request.model_dump(exclude={"release_id", "release_hash"})
    filters["lifecycle"] = effective_identity_lifecycle(
        dataset_id, filters["lifecycle"], subject_id=filters["subject_id"], query=filters["query"],
    )
    try:
        rows = identity_dataset_rows(
            dataset_id, release=bound, **filters,
        )
    except DataProductError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from exc
    catalog_value = release_catalog(bound)
    material = {"binding": catalog_value["binding"], "catalog_version": catalog_value["catalog_version"],
                "dataset_id": dataset_id,
                "filters": filters}
    filter_hash = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
    offset = 0
    if cursor:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii") + b"=" * (-len(cursor) % 4)))
            if decoded["filter_hash"] != filter_hash or type(decoded["offset"]) is not int or not 0 <= decoded["offset"] < len(rows):
                raise ValueError("cursor does not bind fixed identity filters")
            offset = decoded["offset"]
        except (ValueError, KeyError, TypeError, UnicodeError, binascii.Error) as exc:
            raise HTTPException(status_code=400, detail={"code": "invalid_identity_cursor"}) from exc
    next_cursor = None
    if offset + limit < len(rows):
        token = json.dumps({"filter_hash": filter_hash, "offset": offset + limit}, sort_keys=True)
        next_cursor = base64.urlsafe_b64encode(token.encode()).decode("ascii").rstrip("=")
    return {
        "schema_version": "fr_data_product_identity_preview_v1", "dataset_id": dataset_id,
        "catalog_version": catalog_value["catalog_version"], "binding": catalog_value["binding"],
        "filters": filters,
        "logical_row_count": len(rows), "logical_row_count_status": "exact_for_filters",
        "preview_row_count": len(rows[offset:offset + limit]),
        "rows": rows[offset:offset + limit], "next_cursor": next_cursor,
        "lifecycle_filter_status": (
            "not_applicable" if dataset_id.endswith("identifier_history") else "available_for_accepted_identities"
        ),
    }


@router.post("/identity-preview-export/{dataset_id}")
def identity_preview_export(
    dataset_id: str, request: IdentityReadRequest,
    limit: int = Query(default=100, ge=1, le=500), cursor: str | None = Query(default=None, max_length=512),
) -> Response:
    result = identity_preview(dataset_id, request, limit=limit, cursor=cursor)
    fields = IDENTITY_FIELDS.get(dataset_id)
    if fields is None:
        raise HTTPException(status_code=409, detail={"code": "logical_dataset_not_exposed"})
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["catalog_version", "release_id", "release_hash", "dataset_id", *fields])
    for row in result["rows"]:
        writer.writerow([result["catalog_version"], result["binding"]["release_id"],
                         result["binding"]["release_hash"], dataset_id,
                         *[row.get(field) for field in fields]])
    return Response(
        content="\ufeff" + stream.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="fr-{dataset_id}-current-preview.csv"',
                 "X-FR-Export-Scope": "current_preview",
                 "X-FR-Catalog-Version": result["catalog_version"]},
    )


@router.post("/export-jobs/identity/{dataset_id}")
def start_identity_export(
    dataset_id: str, request: IdentityExportRequest, background: BackgroundTasks,
) -> dict[str, Any]:
    bound = _release(request.release_id, request.release_hash)
    version = release_catalog(bound)["catalog_version"]
    filters = request.model_dump(exclude={"release_id", "release_hash", "scope", "fields"})
    try:
        sweep_expired()
        state = create_identity_job(dataset_id, release=bound, filters=filters,
                                    fields=request.fields, scope=request.scope,
                                    catalog_version=version)
    except DataProductError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from exc
    background.add_task(run_identity_job, state["job_id"], release=bound)
    return state


@router.post("/export-jobs/daily/{dataset_id}")
def start_daily_export(
    dataset_id: str, request: ResearchTableRequest, background: BackgroundTasks,
) -> dict[str, Any]:
    bound = _release(request.release_id, request.release_hash)
    catalog_value = release_catalog(bound)
    dataset = next((row for row in catalog_value["datasets"] if row["dataset_id"] == dataset_id), None)
    selection = DAILY_DATASETS.get(dataset_id)
    if dataset is None or selection is None or dataset["export"] != "available":
        raise HTTPException(status_code=409, detail={"code": "logical_dataset_not_exposed"})
    try:
        sweep_expired()
        state = create_daily_job(
            dataset_id, release=bound, catalog_version=catalog_value["catalog_version"],
            universe=request.universe, subject_type=request.subject_type,
            subject_id=request.subject_id, metric_ids=request.metric_ids,
            start=request.start, end=request.end,
        )
    except DataProductError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from exc
    background.add_task(run_daily_job, state["job_id"], release=bound)
    return state


@router.get("/export-jobs/{job_id}")
def export_job_status(job_id: str) -> dict[str, Any]:
    try:
        return job_status(job_id)
    except DataProductError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from exc


@router.post("/export-jobs/{job_id}/cancel")
def export_job_cancel(job_id: str) -> dict[str, Any]:
    try:
        return cancel_job(job_id)
    except DataProductError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from exc


@router.get("/export-jobs/{job_id}/download")
def export_job_download(job_id: str) -> FileResponse:
    try:
        path = completed_output(job_id)
    except DataProductError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from exc
    return FileResponse(path, media_type="text/csv; charset=utf-8", filename=f"{job_id}.csv")


@router.get("/object-context/{dataset_id}")
def object_context(
    dataset_id: str, subject_id: str, subject_type: str | None = None,
    release_id: str | None = None, release_hash: str | None = None,
) -> dict[str, Any]:
    """Return stable ordinary/Explorer navigation by durable object identity."""
    bound = _release(release_id, release_hash)
    catalog_value = release_catalog(bound)
    known = {row["dataset_id"] for row in catalog_value["datasets"]}
    if dataset_id not in known:
        raise HTTPException(status_code=404, detail={"code": "logical_dataset_not_found"})
    if dataset_id.startswith("equity."):
        if dataset_id not in {"equity.listings", "equity.identifier_history", "equity.daily_market"} or subject_type not in (None, "listing"):
            raise HTTPException(status_code=400, detail={"code": "object_selection_mismatch"})
        try:
            listing = ChinaEquityQueryService.for_release(bound).listing_by_id(subject_id)["listing"]
        except ChinaEquityQueryError as exc:
            raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from exc
        ordinary = {"universe": "Equity", "subject_type": "listing", "subject_id": subject_id,
                    "display_name": listing["display_name"], "exchange": listing["exchange"],
                    "external_code": listing["external_code"], "lifecycle_class": listing["lifecycle_class"]}
        history = {
            "codes": [{"value": row.get("code"), "effective_start": row.get("effective_from"),
                       "effective_end": row.get("effective_to")}
                      for row in listing["code_aliases"]],
            "names": [{"value": row.get("value"), "effective_start": row.get("effective_from"),
                       "effective_end": row.get("effective_to")}
                      for row in listing["name_aliases"]],
        }
        explorer = ["equity.listings", "equity.identifier_history", "equity.daily_market"]
    elif dataset_id.startswith("fund."):
        expected = {"fund.products": "fund", "fund.share_classes": "fund_share_class",
                    "fund.listings": "listing", "fund.share_class_daily": "fund_share_class",
                    "fund.listing_daily": "listing"}
        kind = subject_type or expected.get(dataset_id)
        if kind is None or (dataset_id != "fund.identifier_history" and kind != expected.get(dataset_id)) or kind not in {"fund", "fund_share_class", "listing"}:
            raise HTTPException(status_code=400, detail={"code": "object_selection_mismatch"})
        owner = ChinaPublicFundQueryService.for_binding(
            access_mode="release", snapshot_id=bound.snapshot_id,
            manifest_sha256=str(bound.component("CN_PUBLIC_FUND")["manifest_sha256"]), release=bound,
        )
        try:
            detail = owner.subject(kind, subject_id)
        except FundQueryError as exc:
            raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from exc
        subject = detail["subject"]
        ordinary = {"universe": "Fund", "subject_type": kind, "subject_id": subject_id,
                    "display_name": subject["attributes"].get("display_name"),
                    "lifecycle_class": None}
        try:
            raw = owner._control_view().subject(kind, subject_id)
            if raw is None:
                raise LifecycleEvidenceError("accepted Fund subject is absent from its release control owner")
            evidence = release_lifecycle_evidence(bound)
            projected = fund_lifecycle(raw, kind=kind, evidence=evidence)
        except LifecycleEvidenceError:
            evidence = None
            projected = {"lifecycle_class": None, "effective_end": subject.get("effective_end"),
                         "estimated_delisting_date": None}
        ordinary["lifecycle_class"] = projected["lifecycle_class"]
        ordinary["effective_end"] = projected["effective_end"]
        if kind == "listing":
            ordinary["estimated_delisting_date"] = projected["estimated_delisting_date"]
        history = {"aliases": [{"value": row.get("alias_value"), "type": row.get("alias_type"),
                                 "effective_start": row.get("effective_start"),
                                 "effective_end": (None if evidence and kind == "listing" and subject_id in evidence.unproved_fund_listing_ends
                                                   else row.get("effective_end"))}
                                for row in detail["aliases"]]}
        related_objects = []
        for relation in detail["relationships"]:
            if relation["from_type"] == kind and relation["from_id"] == subject_id:
                other_type, other_id = relation["to_type"], relation["to_id"]
            else:
                other_type, other_id = relation["from_type"], relation["from_id"]
            if other_type not in {"fund", "fund_share_class", "listing"}:
                continue
            related_objects.append({
                "relationship_type": relation["relationship_type"],
                "object_type": other_type, "object_id": other_id,
                "display_name": relation.get("related_canonical_name"),
                "effective_start": relation.get("effective_start"),
                "effective_end": relation.get("effective_end"),
            })
        explorer = ["fund.products", "fund.share_classes", "fund.listings", "fund.identifier_history"]
        if kind == "fund_share_class":
            explorer.append("fund.share_class_daily")
        elif kind == "listing":
            explorer.append("fund.listing_daily")
    else:
        raise HTTPException(status_code=409, detail={"code": "logical_dataset_not_exposed"})
    return {"schema_version": "fr_data_product_object_context_v1",
            "binding": catalog_value["binding"], "catalog_version": catalog_value["catalog_version"],
            "ordinary_object": ordinary, "identity_history": history,
            "related_objects": related_objects if dataset_id.startswith("fund.") else [],
            "explorer_datasets": [dataset for dataset in explorer if dataset in known],
            "navigation_identity": "durable_subject_not_external_code"}


@router.post("/research-table")
def table(request: ResearchTableRequest) -> dict[str, Any]:
    try:
        return research_table(**request.model_dump(exclude={"release_id", "release_hash"}),
                              release=_release(request.release_id, request.release_hash))
    except DataProductError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


def _dataset_table(dataset_id: str, request: ResearchTableRequest) -> tuple[dict[str, Any], dict[str, Any]]:
    bound = _release(request.release_id, request.release_hash)
    catalog_value = release_catalog(bound)
    dataset = next((row for row in catalog_value["datasets"] if row["dataset_id"] == dataset_id), None)
    if dataset is None:
        raise HTTPException(status_code=404, detail={"code": "logical_dataset_not_found"})
    selection = DAILY_DATASETS.get(dataset_id)
    if selection is None or dataset["preview"] != "available":
        raise HTTPException(status_code=409, detail={"code": "logical_dataset_not_exposed"})
    universe, subject_type, metrics = selection
    if request.universe != universe or request.subject_type not in (None, subject_type) or not set(request.metric_ids) <= metrics:
        raise HTTPException(status_code=400, detail={"code": "dataset_selection_mismatch"})
    try:
        # Explorer's preview/export contract is one bounded owner query, not
        # an accidental browser-driven full-history scan.
        from datetime import date
        if (date.fromisoformat(request.end) - date.fromisoformat(request.start)).days > 366:
            raise DataProductError("invalid_date_range", "Explorer interval must be at most 366 days")
        value = research_table(
            universe=universe, subject_type=subject_type, subject_id=request.subject_id,
            metric_ids=request.metric_ids, start=request.start, end=request.end,
            max_rows=request.max_rows, release=bound,
        )
    except DataProductError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_date_range"}) from exc
    return catalog_value, value


@router.post("/preview/{dataset_id}")
def preview(dataset_id: str, request: ResearchTableRequest,
            limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    catalog_value, value = _dataset_table(dataset_id, request)
    return {
        "schema_version": "fr_data_product_preview_v1",
        "dataset_id": dataset_id, "catalog_version": catalog_value["catalog_version"],
        "binding": value["binding"], "row_grain": value["row_grain"],
        "filters": {"subject_id": request.subject_id, "start": request.start,
                    "end": request.end, "metric_ids": request.metric_ids},
        "status": value["status"], "field_failures": value["field_failures"],
        "logical_row_count": value["row_count"] if value["status"] == "complete" else None,
        "logical_row_count_status": "exact_for_filters" if value["status"] == "complete" else "unknown_partial_failure",
        "preview_row_count": min(value["row_count"], limit),
        "rows": value["rows"][:limit],
        "has_more": value["row_count"] > limit,
        "export_scopes": ["preview", "all_matching_bounded_interval"],
    }


@router.post("/export/{dataset_id}")
def export(dataset_id: str, request: ResearchTableRequest,
           scope: Literal["preview", "all_matching_bounded_interval"] = "all_matching_bounded_interval",
           preview_limit: int = Query(default=100, ge=1, le=500)) -> Response:
    catalog_value, value = _dataset_table(dataset_id, request)
    if value["status"] != "complete":
        raise HTTPException(status_code=409, detail={"code": "incomplete_field_retrieval_cannot_export_as_complete"})
    rows = value["rows"][:preview_limit] if scope == "preview" else value["rows"]
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["catalog_version", "release_id", "release_hash", "dataset_id", "subject_type", "subject_id",
                     "economic_time", "metric_id", "observation_status", "value", "unit", "currency", "scale",
                     "time_role", "series_id", "provenance_json", "support_source_observation_id"])
    series_by_metric = {item["metric_id"]: item.get("series_id") for item in value["fields"]}
    for row in rows:
        for metric in request.metric_ids:
            cell = row["cells"][metric]
            writer.writerow([
                catalog_value["catalog_version"], value["binding"]["release_id"], value["binding"]["release_hash"],
                dataset_id, value["subject"]["type"], value["subject"]["id"], row["economic_time"], metric,
                "returned" if cell is not None else "no_returned_observation",
                cell.get("value") if cell else None, cell.get("unit") if cell else None,
                cell.get("currency") if cell else None, cell.get("scale") if cell else None,
                cell.get("time_role") if cell else None, series_by_metric.get(metric),
                json.dumps(cell.get("provenance"), ensure_ascii=False, sort_keys=True) if cell else None,
                (cell.get("support_trace") or {}).get("source_observation_id") if cell else None,
            ])
    return Response(
        content="\ufeff" + stream.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="fr-{dataset_id}-{scope}.csv"',
                 "X-FR-Export-Scope": scope, "X-FR-Catalog-Version": catalog_value["catalog_version"]},
    )
