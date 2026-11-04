from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.app.core.china_public_fund_query import (
    ChinaPublicFundQueryService,
    FundQueryError,
    fund_release_catalog,
)
from backend.app.core.china_public_fund_update import (
    FundIdentityReviewRequired,
    FundUpdateConfig,
    FundUpdateError,
    run_user_triggered_fund_update,
    update_state,
)
from backend.app.core.normal_update_publication import run_fund_update_and_publish
from backend.app.core.desired_data_profile import DesiredDataProfileRepository
from backend.app.core.operation_lifecycle import (
    OperationRegistrationUnavailable,
    record_operation_result,
    record_operation_started,
)
from backend.app.core.diagnostics import (
    ErrorClass,
    current_request_id,
    diagnostic_http_exception,
    diagnostic_result_http_exception,
    log_event,
    log_serving_binding,
    new_operation_id,
    operation_context,
)
from backend.app.core.storage_profile import resolve_temporary_workspace_path
from backend.app.core.storage_profile import resolve_control_plane_path


router = APIRouter(prefix="/api/funds", tags=["china-public-fund-query"])
update_router = APIRouter(prefix="/api/funds", tags=["china-public-fund-update"])


class TimeSeriesRequest(BaseModel):
    subject_type: str
    subject_id: str
    metric_id: str
    start: str | None = None
    end: str | None = None
    max_rows: int = Field(default=20_000, ge=1, le=50_000)


class BatchTimeSeriesRequest(BaseModel):
    requests: list[TimeSeriesRequest] = Field(min_length=1, max_length=8)


class SnapshotSessionRequest(BaseModel):
    access_mode: Literal["active", "validated_review"] = "active"
    snapshot_id: str | None = None
    manifest_sha256: str | None = None


def _run(call):
    try:
        return call()
    except FundQueryError as exc:
        raise diagnostic_http_exception(exc) from exc


def _bound_service(
    access_mode: Literal["active", "release", "validated_review"] = Query(default="active"),
    snapshot_id: str | None = None,
    manifest_sha256: str | None = None,
    release_id: str | None = None,
    release_hash: str | None = None,
) -> ChinaPublicFundQueryService:
    if access_mode == "release":
        if not release_id or not release_hash:
            raise HTTPException(
                status_code=400,
                detail={"code": "explicit_release_binding_required", "message": "release_id and release_hash are required"},
            )
        service = _run(lambda: ChinaPublicFundQueryService.for_registered_release(
            release_id=release_id, release_hash=release_hash,
        ))
    else:
        service = _run(lambda: ChinaPublicFundQueryService.for_binding(
            access_mode=access_mode,
            snapshot_id=snapshot_id,
            manifest_sha256=manifest_sha256,
        ))
    log_serving_binding("china_public_fund", service.snapshot_metadata())
    return service


BoundFundService = Annotated[ChinaPublicFundQueryService, Depends(_bound_service)]


@router.get("/releases")
def fund_releases() -> dict[str, Any]:
    return fund_release_catalog()


@update_router.get("/update-state")
def fund_update_state() -> dict[str, Any]:
    """Read the manual Fund updater without starting background work."""
    return update_state()


@update_router.post("/update")
def update_china_public_fund() -> dict[str, Any]:
    """Execute one user-triggered update; the caller supplies intent only."""
    operation_id = new_operation_id("fund_update")
    with operation_context(operation_id):
        log_event("operation_started", capability="china_public_fund", stage="update_entry")
        runtime_root = resolve_temporary_workspace_path("china_public_fund_user_update") / "runs" / operation_id
        try:
            record_operation_started(
                operation_id,
                operation_type="fund_update",
                scope="Fund",
                runtime_root=runtime_root,
                request_id=current_request_id(),
            )
        except OperationRegistrationUnavailable as exc:
            result = {
                "status": "rejected",
                "result": "operation_registration_unavailable",
                "operation_accepted": False,
                "operation_id": None,
                "attempted_operation_id": operation_id,
                "retryable": True,
                "error_code": "operation_registration_unavailable",
                "error_class": ErrorClass.CONTROL_PLANE_UNAVAILABLE.value,
                "error": "the operation could not be durably registered; no financial work was started",
                "provider_calls": 0,
            }
            log_event(
                "operation_rejected",
                level=30,
                capability="china_public_fund",
                stage="operation_registration",
                error_code="operation_registration_unavailable",
                error_type=type(exc).__name__,
            )
            raise diagnostic_result_http_exception(
                result, status_code=503, code="operation_registration_unavailable"
            ) from exc
        try:
            if not DesiredDataProfileRepository(resolve_control_plane_path()).is_component_configured("CN_PUBLIC_FUND"):
                result = {
                    "status": "blocked",
                    "result": "blocked",
                    "operation_id": operation_id,
                    "error_code": "no_data_scope_configured",
                    "error_class": ErrorClass.REQUEST_INVALID.value,
                    "error": "no enabled Fund data scope is configured",
                    "provider_calls": 0,
                    "publication": {"status": "not_attempted", "reason": "no_data_scope_configured", "pointer_changed": False},
                }
                record_operation_result(operation_id, result, operation_type="fund_update", scope="Fund")
                raise diagnostic_result_http_exception(result, status_code=409, code="no_data_scope_configured")
            result = run_fund_update_and_publish(
                FundUpdateConfig(
                    output_root=resolve_temporary_workspace_path("china_public_fund_user_update"),
                    as_of_date=date.today().isoformat(),
                ),
                update_runner=run_user_triggered_fund_update,
                run_id=operation_id,
            )
            result["operation_id"] = operation_id
            incomplete = str(result.get("result") or "").startswith(("incomplete_", "untrustworthy_"))
            if incomplete:
                result["error_class"] = ErrorClass.PROVIDER_OR_UPDATE_FAILED.value
            try:
                record_operation_result(operation_id, result, operation_type="fund_update", scope="Fund")
            except Exception as exc:
                log_event("operation_lifecycle_record_failed", level=30, capability="china_public_fund", stage="operation_result", error_type=type(exc).__name__)
            log_event(
                "operation_completed" if not incomplete else "operation_incomplete",
                level=20 if not incomplete else 30,
                capability="china_public_fund",
                stage="validated_update_result",
                result=result.get("result"),
                error_class=result.get("error_class"),
                predecessor_snapshot_id=result.get("predecessor_snapshot_id"),
                successor_snapshot_id=result.get("successor_snapshot_id"),
            )
            if incomplete:
                raise diagnostic_result_http_exception(
                    result, status_code=503, code="fund_update_incomplete"
                )
            return result
        except HTTPException:
            raise
        except FundIdentityReviewRequired as exc:
            try:
                record_operation_result(operation_id, {"status": "failed", "error_class": ErrorClass.IDENTITY_UNRESOLVED_OR_AMBIGUOUS.value, "error_type": "fund_identity_review_required", "error": str(exc)}, operation_type="fund_update", scope="Fund")
            except Exception as record_exc:
                log_event("operation_lifecycle_record_failed", level=30, capability="china_public_fund", stage="identity_resolution", error_type=type(record_exc).__name__)
            log_event("operation_failed", level=30, capability="china_public_fund", stage="identity_resolution", error_code="fund_identity_review_required")
            exc.code = "fund_identity_review_required"
            exc.message = str(exc)
            exc.status_code = 409
            raise diagnostic_http_exception(exc) from exc
        except FundUpdateError as exc:
            try:
                record_operation_result(operation_id, {"status": "failed", "error_class": ErrorClass.PROVIDER_OR_UPDATE_FAILED.value, "error_type": "fund_update_failed", "error": str(exc)}, operation_type="fund_update", scope="Fund")
            except Exception as record_exc:
                log_event("operation_lifecycle_record_failed", level=30, capability="china_public_fund", stage="update_execution", error_type=type(record_exc).__name__)
            log_event("operation_failed", level=40, capability="china_public_fund", stage="update_execution", error_code="fund_update_failed")
            exc.code = "fund_update_failed"
            exc.message = str(exc)
            exc.status_code = 503
            raise diagnostic_http_exception(exc) from exc
        except Exception as exc:
            try:
                record_operation_result(
                    operation_id,
                    {"status": "failed", "error_type": type(exc).__name__, "error_code": "fund_update_internal_failure", "error_class": ErrorClass.INTERNAL_FAILURE.value},
                    operation_type="fund_update",
                    scope="Fund",
                )
            except Exception as record_exc:
                log_event("operation_lifecycle_record_failed", level=30, capability="china_public_fund", stage="internal_failure", error_type=type(record_exc).__name__)
            raise


@router.post("/session")
def establish_fund_session(request: SnapshotSessionRequest) -> dict[str, Any]:
    service = _run(lambda: ChinaPublicFundQueryService.for_binding(
        access_mode=request.access_mode,
        snapshot_id=request.snapshot_id,
        manifest_sha256=request.manifest_sha256,
    ))
    metadata = service.snapshot_metadata()
    binding = {
        "access_mode": request.access_mode,
        "snapshot_id": service.snapshot.snapshot_id,
        "manifest_sha256": service.snapshot.manifest_sha256,
    }
    if metadata.get("release_id") and metadata.get("release_hash"):
        binding = {
            "access_mode": "release",
            "release_id": metadata["release_id"],
            "release_hash": metadata["release_hash"],
            "snapshot_id": service.snapshot.snapshot_id,
            "manifest_sha256": service.snapshot.manifest_sha256,
        }
    return {
        "status": "ready",
        "universe": "Fund",
        "jurisdiction": "CN",
        "snapshot": metadata,
        "binding": binding,
    }


@router.get("/search")
def search_funds(
    service: BoundFundService,
    q: str = Query(min_length=1, max_length=200),
    alias_effective_date: str | None = None,
    subject_type: list[str] | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    complete: bool = False,
    market: str = "All",
    cursor: str | None = Query(default=None, max_length=512),
) -> dict[str, Any]:
    return _run(lambda: service.search(
        q, alias_effective_date=alias_effective_date,
        subject_types=subject_type, limit=limit,
        complete=complete, market=market, cursor=cursor,
    ))


@router.get("/subject")
def fund_subject(service: BoundFundService, subject_type: str, subject_id: str) -> dict[str, Any]:
    return _run(lambda: service.subject(subject_type, subject_id))


@router.get("/timeseries")
def fund_time_series(
    service: BoundFundService,
    subject_type: str,
    subject_id: str,
    metric_id: str,
    start: str | None = None,
    end: str | None = None,
    max_rows: int = Query(default=20_000, ge=1, le=50_000),
) -> dict[str, Any]:
    return _run(lambda: service.time_series(
        subject_type=subject_type, subject_id=subject_id, metric_id=metric_id,
        start=start, end=end, max_rows=max_rows,
    ))


@router.post("/timeseries/batch")
def fund_time_series_batch(request: BatchTimeSeriesRequest, service: BoundFundService) -> dict[str, Any]:
    return _run(lambda: service.batch_time_series(
        [item.model_dump() for item in request.requests]
    ))


@router.get("/nonpromoted-summary")
def fund_nonpromoted_summary(service: BoundFundService, external_code: str | None = None) -> dict[str, Any]:
    return _run(lambda: service.nonpromoted_summary(
        external_code=external_code
    ))
