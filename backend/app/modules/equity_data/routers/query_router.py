from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.app.core.china_equity_query import ChinaEquityQueryError, ChinaEquityQueryService
from backend.app.core.diagnostics import diagnostic_http_exception, log_serving_binding


router = APIRouter(prefix="/api/equity/china", tags=["china-equity-query"])


def _service(
    release_id: str | None = None,
    release_hash: str | None = None,
) -> ChinaEquityQueryService:
    try:
        if release_id or release_hash:
            if not release_id or not release_hash:
                raise ChinaEquityQueryError(
                    "explicit_release_binding_required",
                    "release_id and release_hash are both required for a pinned release",
                )
            service = ChinaEquityQueryService.for_registered_release(
                release_id=release_id, release_hash=release_hash,
            )
        else:
            service = ChinaEquityQueryService.active()
        log_serving_binding("china_equity", service.snapshot_metadata())
        return service
    except ChinaEquityQueryError as exc:
        raise diagnostic_http_exception(exc) from exc


def _run(call):
    try:
        return call()
    except ChinaEquityQueryError as exc:
        raise diagnostic_http_exception(exc) from exc


@router.get("/session")
def establish_china_equity_session(
    service: ChinaEquityQueryService = Depends(_service),
) -> dict[str, Any]:
    snapshot = service.snapshot_metadata()
    return {
        "status": "ready",
        "universe": "Equity",
        "jurisdiction": "CN",
        "snapshot": snapshot,
        "binding": {
            "release_id": snapshot["release_id"],
            "release_hash": snapshot["release_hash"],
        },
    }


@router.get("/resolve")
def resolve_listing(
    exchange: str,
    code: str,
    alias_effective_date: str,
    service: ChinaEquityQueryService = Depends(_service),
) -> dict[str, Any]:
    """Resolve an effective exchange alias to the accepted listing episode."""
    return _run(lambda: service.resolve_listing(
        exchange=exchange, code=code, alias_effective_date=alias_effective_date,
    ))


@router.get("/search")
def search_listings(
    q: str,
    limit: int = Query(default=20, ge=1, le=100),
    market: str = "All",
    exchange: str | None = None,
    lifecycle: str = "All",
    cursor: str | None = Query(default=None, max_length=512),
    service: ChinaEquityQueryService = Depends(_service),
) -> dict[str, Any]:
    """Return release-bound candidates without guessing an economic identity."""
    return _run(lambda: service.search(
        q, limit=limit, market=market, exchange=exchange,
        lifecycle=lifecycle, cursor=cursor,
    ))


@router.get("/timeseries")
def time_series(
    listing_id: str,
    metric_id: str,
    start: str,
    end: str,
    adjustment_basis: str = "unadjusted",
    max_rows: int = Query(default=5_000, ge=1, le=5_000),
    service: ChinaEquityQueryService = Depends(_service),
) -> dict[str, Any]:
    return _run(lambda: service.time_series(
        listing_id=listing_id,
        metric_id=metric_id,
        adjustment_basis=adjustment_basis,
        start=start,
        end=end,
        max_rows=max_rows,
    ))
