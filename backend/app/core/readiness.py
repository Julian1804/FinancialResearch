"""Bounded readiness probe for the authoritative Fund + China Equity V1."""

from __future__ import annotations

import logging
from typing import Any, Callable

from backend.app.core.china_equity_query import ChinaEquityQueryService
from backend.app.core.china_public_fund_query import ChinaPublicFundQueryService, FUND_UNIVERSE
from backend.app.core.diagnostics import classify_error, log_event, log_serving_binding
from backend.app.core.serving_publication import has_committed_serving_transition
from backend.app.core.serving_release import ActiveReleaseAbsent, PinnedServingRelease, pin_serving_release
from backend.app.core.storage_profile import resolve_control_plane_path


class ReadinessContractError(RuntimeError):
    code = "serving_release_context_mismatch"
    status_code = 503


def active_v1_readiness(
    *,
    release_loader: Callable[[], PinnedServingRelease] = pin_serving_release,
) -> dict[str, Any]:
    """Resolve both serving contracts against one pinned release without data scans."""
    try:
        release = release_loader()
        fund = ChinaPublicFundQueryService.for_binding(
            access_mode="release",
            snapshot_id=release.snapshot_id,
            manifest_sha256=str(release.component(FUND_UNIVERSE)["manifest_sha256"]),
            release=release,
        )
        equity = ChinaEquityQueryService.for_release(release)
        fund_metadata = fund.snapshot_metadata()
        equity_metadata = equity.snapshot_metadata()
        if fund_metadata.get("release_id") != equity_metadata.get("release_id"):
            raise ReadinessContractError("Fund and China Equity resolved different serving releases")
        if fund_metadata.get("database_generation_id") != equity_metadata.get("database_generation_id"):
            raise ReadinessContractError("Fund and China Equity resolved different database generations")
        log_serving_binding("china_public_fund", fund_metadata)
        log_serving_binding("china_equity", equity_metadata)
        return {
            "status": "ready",
            "service": "financial_research_backend",
            "release_id": release.release_id,
            "release_hash": release.release_hash,
            "snapshot_id": release.snapshot_id,
            "database_generation_id": release.database_generation_id,
            "checks": {
                "china_public_fund": {"status": "ready", "snapshot_id": fund_metadata["snapshot_id"]},
                "china_equity": {"status": "ready", "snapshot_id": equity_metadata["snapshot_id"]},
            },
            "probe_scope": "serving_contract_and_required_metadata_only",
        }
    except ActiveReleaseAbsent as exc:
        try:
            first_publication_pending = not has_committed_serving_transition(resolve_control_plane_path())
        except Exception as control_exc:
            exc = control_exc
        else:
            if first_publication_pending:
                code = "first_publication_pending"
                log_event(
                    "readiness_serving_unavailable",
                    level=logging.INFO,
                    stage="pre_publication",
                    error_class="serving_state_invalid",
                    error_code=code,
                )
                return {
                    "status": "not_ready",
                    "service": "financial_research_backend",
                    "error_class": "serving_state_invalid",
                    "error_code": code,
                    "checks": {},
                    "probe_scope": "serving_contract_and_required_metadata_only",
                }
        return _readiness_failure(exc)
    except Exception as exc:
        return _readiness_failure(exc)


def _readiness_failure(exc: Exception) -> dict[str, Any]:
    code = str(getattr(exc, "code", type(exc).__name__))
    status_code = int(getattr(exc, "status_code", 503))
    error_class = classify_error(code, status_code).value
    log_event(
        "readiness_failed",
        level=logging.ERROR,
        stage="serving_resolution",
        error_class=error_class,
        error_code=code,
    )
    return {
        "status": "not_ready",
        "service": "financial_research_backend",
        "error_class": error_class,
        "error_code": code,
        "checks": {},
        "probe_scope": "serving_contract_and_required_metadata_only",
    }
