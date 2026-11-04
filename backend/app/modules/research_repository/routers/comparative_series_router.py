from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.app.core.china_equity_query import ChinaEquityQueryError
from backend.app.core.china_public_fund_query import FundQueryError
from backend.app.core.comparative_series_research import (
    ALIGNMENT_POLICY,
    ComparativeResearchError,
    ComparativeResearchSpec,
    ComparativeSeriesSelection,
    DEFAULT_CALCULATION_SPEC,
    RESEARCH_SCHEMA_VERSION,
    run_comparative_research,
)
from backend.app.core.diagnostics import (
    diagnostic_http_exception,
    log_event,
    log_serving_binding,
    new_operation_id,
    operation_context,
)


router = APIRouter(prefix="/api/research", tags=["comparative-series-research"])


class SeriesSelectionRequest(BaseModel):
    universe: Literal["Fund", "Equity"]
    subject_type: str
    subject_id: str
    metric_id: str
    adjustment_basis: str | None = None


class ComparativeSeriesRequest(BaseModel):
    selections: list[SeriesSelectionRequest] = Field(min_length=1)
    start: str
    end: str
    alignment_policy: str = ALIGNMENT_POLICY
    calculation_spec: dict[str, Any] = Field(default_factory=lambda: dict(DEFAULT_CALCULATION_SPEC))


@router.get("/comparative-series/policy")
def comparative_series_policy() -> dict[str, Any]:
    from backend.app.core.comparative_series_research import policy_descriptor

    return policy_descriptor()


@router.post("/comparative-series/run")
def comparative_series_run(request: ComparativeSeriesRequest) -> dict[str, Any]:
    operation_id = new_operation_id("research_run")
    with operation_context(operation_id):
        log_event("operation_started", capability="comparative_series_research", stage="research_entry")
        try:
            selections = tuple(
                ComparativeSeriesSelection(**selection.model_dump())
                for selection in request.selections
            )
            spec = ComparativeResearchSpec(
                selections=selections,
                start=request.start,
                end=request.end,
                alignment_policy=request.alignment_policy,
                calculation_spec=request.calculation_spec,
            )
            result = run_comparative_research(spec)
        except ComparativeResearchError as exc:
            log_event("operation_failed", level=30, capability="comparative_series_research", stage="research_execution", error_code=exc.code)
            raise diagnostic_http_exception(exc) from exc
        except (FundQueryError, ChinaEquityQueryError) as exc:
            log_event("operation_failed", level=30, capability="comparative_series_research", stage="universe_query", error_code=exc.code)
            raise diagnostic_http_exception(exc) from exc
        log_serving_binding("comparative_series_research", result["release"])
        result["operation_id"] = operation_id
        result["research_schema_version"] = RESEARCH_SCHEMA_VERSION
        log_event(
            "operation_completed",
            capability="comparative_series_research",
            stage="research_result",
            result_status=result["status"],
            run_id=result["run_id"],
            release_id=result["release"].get("release_id"),
        )
        return result
