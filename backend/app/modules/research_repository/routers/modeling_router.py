from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import SpooledTemporaryFile, TemporaryDirectory
from typing import Any
import zipfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.app.core.china_equity_query import ChinaEquityQueryService
from backend.app.core.china_public_fund_query import ChinaPublicFundQueryService
from backend.app.core.modeling_platform import (
    ModelingDatasetSpec, ModelingError, ModelingRunStore, ModelingVariable,
    build_dataset, digest, export_run, model_inventory, validate_model_request,
    validate_optimization_request,
)
from backend.app.core.serving_release import pin_serving_release


router = APIRouter(prefix="/api/research/modeling", tags=["modeling"])
STORE = ModelingRunStore()


class VariableRequest(BaseModel):
    name: str
    series_key: str
    transformations: list[dict[str, Any]] = Field(default_factory=list)
    role: str = "X"


class DatasetRequest(BaseModel):
    y: list[VariableRequest] = Field(min_length=1)
    x: list[VariableRequest] = Field(default_factory=list)
    start: str | None = None
    end: str | None = None
    shape: str = "supervised"
    horizon: int = 0
    time_features: list[dict[str, Any]] = Field(default_factory=list)
    missing_strategy: str = "drop"
    missing_options: dict[str, Any] = Field(default_factory=dict)
    split: dict[str, Any] = Field(default_factory=lambda: {"kind": "chronological", "train_fraction": 0.8})
    validation: dict[str, Any] = Field(default_factory=lambda: {"kind": "holdout"})
    frequency: str | None = None
    alignment: dict[str, Any] = Field(default_factory=lambda: {"kind": "exact_economic_time"})
    knowledge_cutoff: str | None = None
    release_binding: dict[str, Any] = Field(default_factory=dict)
    label_definition: dict[str, Any] = Field(default_factory=dict)


class PreviewRequest(DatasetRequest):
    model_id: str = "ols"
    parameters: dict[str, Any] = Field(default_factory=dict)
    operation: str = "run"
    comparison_model_ids: list[str] = Field(default_factory=list)
    comparison_parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)
    optimization_search_space: dict[str, list[Any]] = Field(default_factory=dict)
    optimization_budget: int = Field(default=20, ge=1, le=100)
    optimization_seed: int = 0


class RunRequest(BaseModel):
    candidate_id: str
    candidate_digest: str
    model_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ComparisonRequest(BaseModel):
    candidate_id: str
    candidate_digest: str
    model_ids: list[str] = Field(min_length=2)
    parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)


class OptimizationRequest(BaseModel):
    candidate_id: str
    candidate_digest: str
    model_id: str
    search_space: dict[str, list[Any]] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    budget: int = Field(default=20, ge=1, le=100)
    seed: int = 0


def _spec(request: DatasetRequest) -> ModelingDatasetSpec:
    return ModelingDatasetSpec(
        y=tuple(ModelingVariable(**item.model_dump()) for item in request.y),
        x=tuple(ModelingVariable(**item.model_dump()) for item in request.x),
        start=request.start, end=request.end, shape=request.shape, horizon=request.horizon,
        time_features=tuple(request.time_features), missing_strategy=request.missing_strategy,
        missing_options=request.missing_options,
        split=request.split, validation=request.validation, knowledge_cutoff=request.knowledge_cutoff,
        frequency=request.frequency, alignment=request.alignment,
        release_binding=request.release_binding, label_definition=request.label_definition,
    )


def _validate_request_interval(request: DatasetRequest) -> None:
    """Validate the bounded interval at the Modeling API boundary.

    Query owners retain responsibility for their own service and data errors,
    but a malformed or client-invalid interval is a Modeling request error.
    Validating it before release reads keeps that distinction stable across
    Fund and Equity inputs and prevents a Preview candidate from being saved.
    """
    if request.start is None or request.end is None:
        return
    try:
        start = date.fromisoformat(request.start)
        end = date.fromisoformat(request.end)
    except ValueError as exc:
        raise ModelingError(
            "invalid_research_date_range",
            "start and end must be ISO calendar dates",
            422,
        ) from exc
    if start > end or (end - start).days > 366:
        raise ModelingError(
            "invalid_research_date_range",
            "start must not be later than end and the interval must be no longer than 366 days",
            422,
        )


def _series_binding(series_key: str, *, panel: bool) -> tuple[str, str, list[str], str]:
    """Parse a UI binding without making codes or names into identities.

    A normal binding is ``Universe:SubjectType:stable-id:metric``.  Panel
    bindings may use ``Equity:Listings:id1|id2:metric``; each id must be an
    accepted listing identity in the pinned release.  The pipe form is a
    selection convenience, not a second identity registry.
    """
    parts = series_key.split(":")
    # Durable FR IDs themselves contain ':' (for example
    # ``listing:<uuid>``), so only the universe, subject type and terminal
    # metric token are positional.  Never truncate an identity at a colon.
    if len(parts) < 4:
        raise ModelingError("invalid_series_binding", "select a financial object and field")
    universe, subject_type, metric_id = parts[0], parts[1], parts[-1]
    subject_token = ":".join(parts[2:-1])
    if not universe or not subject_type or not subject_token or not metric_id:
        raise ModelingError("invalid_series_binding", "select a financial object and field")
    if panel and universe == "Equity" and subject_type in {"Listings", "Panel"}:
        listing_ids = [item.strip() for item in subject_token.split("|") if item.strip()]
        if len(listing_ids) < 2 or len(listing_ids) != len(set(listing_ids)):
            raise ModelingError("invalid_panel_binding", "panel Equity selection requires at least two distinct accepted listing IDs")
        return universe, subject_type, listing_ids, metric_id
    if panel:
        raise ModelingError("panel_identity_unavailable", "release-bound panel input requires an Equity Listings binding")
    return universe, subject_type, [subject_token], metric_id


def _accepted_listing_entities(equity: ChinaEquityQueryService, listing_ids: list[str]) -> dict[str, str]:
    rows = equity.accepted_listing_rows()
    index: dict[str, str] = {}
    for row in rows:
        listing_id = str(row.get("listing_id") or "")
        entity_id = str(row.get("entity_id") or "")
        if listing_id and entity_id:
            if listing_id in index and index[listing_id] != entity_id:
                raise ModelingError("ambiguous_panel_identity", f"listing {listing_id} maps to multiple durable entities", 409)
            index[listing_id] = entity_id
    missing = [listing_id for listing_id in listing_ids if listing_id not in index]
    if missing:
        raise ModelingError("panel_identity_unavailable", "selected listing is not present in the pinned accepted identity owner", 409, {"listing_ids": missing})
    return {listing_id: index[listing_id] for listing_id in listing_ids}


def _observations_from_release(spec: ModelingDatasetSpec) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    if not spec.start or not spec.end:
        raise ModelingError("bounded_interval_required", "select explicit start and end dates for release-bound Modeling")
    release = pin_serving_release()
    equity = ChinaEquityQueryService.for_release(release)
    fund_component = release.component("CN_PUBLIC_FUND")
    fund = ChinaPublicFundQueryService.for_binding(
        access_mode="release", snapshot_id=release.snapshot_id,
        manifest_sha256=str(fund_component.get("manifest_sha256") or ""), release=release,
    )
    result: dict[str, list[dict[str, Any]]] = {}
    binding_rows: list[dict[str, Any]] = []
    panel_entity_sets: list[set[str]] = []
    accepted_time_roles: dict[str, list[str]] = {}
    for variable in (*spec.y, *spec.x):
        # series_key is a UI-facing stable token generated from the selected
        # object/field binding. It is never passed to SQL or treated as identity.
        universe, subject_type, listing_ids, metric_id = _series_binding(variable.series_key, panel=spec.shape == "panel")
        if universe == "Equity":
            entity_by_listing = _accepted_listing_entities(equity, listing_ids)
            points: list[dict[str, Any]] = []
            for listing_id in listing_ids:
                payload = equity.time_series(
                    listing_id=listing_id, metric_id=metric_id, adjustment_basis="unadjusted",
                    start=spec.start, end=spec.end, max_rows=5_000,
                )
                for point in payload.get("points", []):
                    row = dict(point)
                    # Identity comes from the release-bound accepted owner;
                    # never derive it from provider codes or fact rows.
                    row["entity_id"] = entity_by_listing[listing_id]
                    row["listing_id"] = listing_id
                    points.append(row)
            result[variable.series_key] = points
            panel_entity_sets.append(set(entity_by_listing.values()))
            accepted_time_roles[variable.series_key] = ["observation_date"]
            binding_rows.append({"series_key": variable.series_key, "universe": universe,
                                 "metric_id": metric_id, "listing_ids": listing_ids,
                                 "entity_ids": [entity_by_listing[item] for item in listing_ids],
                                 "accepted_time_roles": ["observation_date"],
                                 "identity_owner": "release_bound_accepted_equity_listing_identity"})
        elif universe == "Fund":
            if len(listing_ids) != 1:
                raise ModelingError("invalid_panel_binding", "Fund multi-entity panel binding is not part of the current release contract")
            subject_id = listing_ids[0]
            payload = fund.time_series(
                subject_type=subject_type, subject_id=subject_id, metric_id=metric_id,
                start=spec.start, end=spec.end, max_rows=50_000,
            )
            result[variable.series_key] = list(payload.get("points", []))
            accepted_time_roles[variable.series_key] = ["nav_date"]
            binding_rows.append({"series_key": variable.series_key, "universe": universe,
                                 "metric_id": metric_id, "subject_id": subject_id,
                                 "accepted_time_roles": ["nav_date"],
                                 "identity_owner": "release_bound_fund_query_contract"})
        else:
            raise ModelingError("unsupported_universe", universe)
    if spec.shape == "panel" and panel_entity_sets and any(item != panel_entity_sets[0] for item in panel_entity_sets[1:]):
        raise ModelingError("panel_binding_mismatch", "all panel variables must select the same durable entity set", 409)
    return result, {"release_id": release.release_id, "release_hash": release.release_hash,
                    "snapshot_id": release.snapshot_id, "database_generation_id": release.database_generation_id,
                    "binding_contract": "release_bound_query_with_accepted_identity_projection",
                    "series_bindings": binding_rows,
                    "accepted_time_roles": accepted_time_roles,
                    "panel_entity_ids": sorted(panel_entity_sets[0]) if spec.shape == "panel" and panel_entity_sets else []}


def _error(exc: ModelingError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message, **exc.detail})


def _preview_execution(request: PreviewRequest) -> dict[str, Any]:
    operation = str(request.operation)
    if operation == "run":
        return {"operation": "run", "model_id": request.model_id, "parameters": dict(request.parameters)}
    if operation == "comparison":
        if len(request.comparison_model_ids) < 2:
            raise ModelingError("comparison_requires_multiple_models", "Preview comparison requires at least two models")
        return {"operation": "comparison", "model_ids": list(request.comparison_model_ids),
                "parameters": {key: dict(value) for key, value in request.comparison_parameters.items()}}
    if operation == "optimization":
        if not request.optimization_search_space:
            raise ModelingError("optimization_search_space_required", "Preview optimization requires a search space")
        return {"operation": "optimization", "model_id": request.model_id,
                "parameters": dict(request.parameters),
                "search_space": {key: list(value) for key, value in request.optimization_search_space.items()},
                "budget": request.optimization_budget, "seed": request.optimization_seed}
    raise ModelingError("invalid_modeling_operation", operation)


def _recover_orphaned_runtime() -> None:
    # This is idempotent and only marks a lock orphaned when its recorded owner
    # process is no longer alive.  It never interrupts a run in this process.
    STORE.mark_orphaned()


@router.get("/models")
def models() -> dict[str, Any]:
    _recover_orphaned_runtime()
    return {"schema_version": "fr_model_catalog_v1", "models": model_inventory()}


@router.post("/preview")
def preview(request: PreviewRequest) -> dict[str, Any]:
    try:
        _recover_orphaned_runtime()
        _validate_request_interval(request)
        spec = _spec(request)
        observations, metadata = _observations_from_release(spec)
        dataset = build_dataset(spec, observations, input_metadata=metadata)
        execution = _preview_execution(request)
        if execution["operation"] == "run":
            validate_model_request(execution["model_id"], dataset, parameters=execution["parameters"])
        elif execution["operation"] == "comparison":
            from backend.app.core.modeling_platform import validate_comparison_request
            validate_comparison_request(execution["model_ids"], dataset, parameters=execution["parameters"])
        else:
            validate_optimization_request(execution["model_id"], dataset,
                                          search_space=execution["search_space"], fixed_parameters=execution["parameters"],
                                          seed=execution["seed"])
        candidate = {"spec": spec.as_dict(), "dataset": dataset, "execution": execution,
                     "model_id": request.model_id, "parameters": request.parameters,
                     "release_binding": metadata or spec.release_binding}
        candidate_digest = digest(candidate)
        candidate_id = STORE.save_candidate(candidate)
        return {"status": "preview_ready", "candidate_id": candidate_id, "candidate_digest": candidate_digest,
                "summary": {"row_count": dataset["row_count"], "raw_row_count": dataset["raw_row_count"],
                            "columns": dataset["columns"], "partitions": dataset["partitions"],
                            "missing_strategy": dataset["missing_strategy"], "input_digest": dataset["input_digest"]}}
    except ModelingError as exc:
        raise _error(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"code": "modeling_preview_failed", "message": str(exc)}) from exc


@router.post("/run")
def run(request: RunRequest) -> dict[str, Any]:
    try:
        _recover_orphaned_runtime()
        candidate = STORE.peek_candidate(request.candidate_id, request.candidate_digest)
        actual = request.candidate_digest
        expected = candidate.get("execution") or {"operation": "run", "model_id": candidate.get("model_id"),
                                                   "parameters": candidate.get("parameters", {})}
        actual_execution = {"operation": "run", "model_id": request.model_id, "parameters": dict(request.parameters)}
        if actual_execution != expected:
            raise ModelingError("candidate_execution_mismatch", "Run configuration differs from Preview", 409)
        row, candidate = STORE.create_from_candidate(request.candidate_id, actual)
        STORE.start_process(row["run_id"], "run", candidate["dataset"], expected["model_id"], expected["parameters"])
        return {"status": "accepted", "run_id": row["run_id"], "candidate_digest": actual}
    except ModelingError as exc:
        raise _error(exc) from exc


@router.post("/compare")
def compare(request: ComparisonRequest) -> dict[str, Any]:
    try:
        _recover_orphaned_runtime()
        candidate = STORE.peek_candidate(request.candidate_id, request.candidate_digest)
        candidate_digest = request.candidate_digest
        expected = candidate.get("execution") or {}
        actual = {"operation": "comparison", "model_ids": list(request.model_ids),
                  "parameters": {key: dict(value) for key, value in request.parameters.items()}}
        if actual != expected:
            raise ModelingError("candidate_execution_mismatch", "comparison configuration differs from Preview", 409)
        row, candidate = STORE.create_from_candidate(request.candidate_id, candidate_digest)
        STORE.update(row["run_id"], model_id="comparison", model_ids=expected["model_ids"], parameters=expected["parameters"],
                     spec=candidate.get("spec"), dataset=candidate.get("dataset"), input_digest=candidate["dataset"]["input_digest"])
        STORE.start_process(row["run_id"], "comparison", candidate["dataset"], expected["model_ids"], expected["parameters"])
        return {"status": "accepted", "run_id": row["run_id"], "candidate_digest": candidate_digest}
    except ModelingError as exc:
        raise _error(exc) from exc


@router.post("/optimize")
def optimize(request: OptimizationRequest) -> dict[str, Any]:
    try:
        _recover_orphaned_runtime()
        candidate = STORE.peek_candidate(request.candidate_id, request.candidate_digest)
        candidate_digest = request.candidate_digest
        expected = candidate.get("execution") or {}
        actual = {"operation": "optimization", "model_id": request.model_id,
                  "parameters": dict(request.parameters),
                  "search_space": {key: list(value) for key, value in request.search_space.items()},
                  "budget": request.budget, "seed": request.seed}
        if actual != expected:
            raise ModelingError("candidate_execution_mismatch", "optimization configuration differs from Preview", 409)
        row, candidate = STORE.create_from_candidate(request.candidate_id, candidate_digest)
        STORE.update(row["run_id"], model_id=expected["model_id"], operation="optimization", search_space=expected["search_space"],
                     parameters=expected["parameters"],
                     budget=expected["budget"], seed=expected["seed"], spec=candidate.get("spec"), dataset=candidate.get("dataset"),
                     input_digest=candidate["dataset"]["input_digest"])
        STORE.start_process(row["run_id"], "optimization", candidate["dataset"], expected["model_id"],
                            {"search_space": expected["search_space"], "fixed_parameters": expected["parameters"]}, expected["budget"], expected["seed"])
        return {"status": "accepted", "run_id": row["run_id"], "candidate_digest": candidate_digest}
    except ModelingError as exc:
        raise _error(exc) from exc


@router.get("/runs")
def list_modeling_runs(limit: int = 20, offset: int = 0) -> dict[str, Any]:
    try:
        _recover_orphaned_runtime()
        return STORE.list_recent(limit=limit, offset=offset)
    except ModelingError as exc:
        raise _error(exc) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail={"code": "modeling_run_list_unavailable",
                                                     "message": "Temporary Modeling history could not be read"}) from exc


@router.get("/runs/{run_id}")
def read_run(run_id: str) -> dict[str, Any]:
    try:
        STORE.mark_orphaned()
        row = STORE.get(run_id)
        if row is None: raise ModelingError("run_not_found", "Modeling run was not found", 404)
        return row
    except ModelingError as exc:
        raise _error(exc) from exc


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict[str, Any]:
    try: return STORE.cancel(run_id)
    except ModelingError as exc: raise _error(exc) from exc


@router.post("/runs/{run_id}/restart")
def restart_run(run_id: str) -> dict[str, Any]:
    try:
        return STORE.restart(run_id)
    except ModelingError as exc:
        raise _error(exc) from exc


@router.get("/runs/{run_id}/export")
def export_model_run(run_id: str) -> StreamingResponse:
    try:
        row = STORE.get(run_id)
        if row is None:
            raise ModelingError("run_not_found", "Modeling run was not found", 404)
        if row.get("status") != "completed" or not isinstance(row.get("result"), dict):
            raise ModelingError("run_not_completed", "Modeling run has no completed result", 409)
        artifact = SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
        try:
            with TemporaryDirectory(prefix="modeling-export-", dir=STORE.root) as directory:
                export_directory = Path(directory)
                export_run(row, export_directory)
                with zipfile.ZipFile(artifact, "w", zipfile.ZIP_DEFLATED) as archive:
                    for path in sorted(export_directory.iterdir()):
                        if path.is_file() and not path.is_symlink():
                            archive.write(path, path.name)
            artifact.seek(0)
        except Exception:
            artifact.close()
            raise
    except ModelingError as exc:
        raise _error(exc) from exc
    except (OSError, ValueError, TypeError, zipfile.BadZipFile) as exc:
        raise HTTPException(status_code=503, detail={"code": "modeling_export_failed",
                                                     "message": "Modeling export could not be generated"}) from exc

    def chunks():
        try:
            while block := artifact.read(1024 * 1024):
                yield block
        finally:
            artifact.close()

    return StreamingResponse(chunks(), media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="fr-modeling-{run_id[9:]}.zip"',
                                      "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
