"""Release-bound Modeling Stage 1 primitives.

The module deliberately keeps model output in ephemeral Research runtime state.
It does not create financial facts or a second query database.  Query owners
provide observations; this module freezes an input table, applies explicit
research transformations and delegates fitting to small model adapters.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
from importlib import metadata as importlib_metadata
import json
import math
import multiprocessing
import os
import re
import signal
import shutil
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from backend.app.core.artifact_io import canonical_json
from backend.app.core.config import RUNTIME_ROOT
from backend.app.core.modeling_family_contracts import capability as _capability_for, inventory as model_inventory
from backend.app.core.writer_runtime_ownership import _pid_alive


SCHEMA_VERSION = "fr_modeling_stage1_v1"
DATASET_SCHEMA_VERSION = "fr_modeling_dataset_v1"
SUPPORTED_TRANSFORMS = frozenset({
    "raw", "percentage_return", "log_return", "first_difference", "log",
    "lag", "rolling_mean", "rolling_volatility", "standardize",
})
SUPPORTED_MISSING = frozenset({"drop", "forward_fill", "backward_fill", "linear", "mean", "median"})
SUPPORTED_SHAPES = frozenset({"supervised", "univariate_time_series", "multivariate_time_series", "panel"})
_RUN_ID = re.compile(r"modeling:[0-9a-f]{32}\Z")


class ModelingError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 400, detail: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code
        self.detail = dict(detail or {})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ModelingVariable:
    name: str
    series_key: str
    transformations: tuple[Mapping[str, Any], ...] = ()
    role: str = "X"

    def __post_init__(self) -> None:
        if not self.name or not self.series_key or self.role not in {"Y", "X"}:
            raise ModelingError("invalid_variable", "variable name, series key and role are required")
        names = [str(operation.get("name", "raw")) for operation in self.transformations]
        for operation, name in zip(self.transformations, names):
            if name not in SUPPORTED_TRANSFORMS:
                raise ModelingError("unsupported_transformation", f"unsupported transformation: {operation}")
        # Stage 1 has a deliberately finite learned-transform grammar.  The
        # standardization parameters are fitted after the chronological split;
        # allowing another operation after that step would silently move it
        # across the split.  Reject that mathematically different chain rather
        # than normalizing it into a different execution order.
        if names.count("standardize") > 1:
            raise ModelingError("invalid_transformation_order", "a variable may contain at most one standardize step")
        if "standardize" in names and names[-1] != "standardize":
            raise ModelingError("invalid_transformation_order", "standardize must be the final transformation in Stage 1")

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "series_key": self.series_key,
                "transformations": [dict(x) for x in self.transformations], "role": self.role}


@dataclass(frozen=True)
class ModelingDatasetSpec:
    y: tuple[ModelingVariable, ...]
    x: tuple[ModelingVariable, ...] = ()
    start: str | None = None
    end: str | None = None
    shape: str = "supervised"
    horizon: int = 0
    time_features: tuple[Mapping[str, Any], ...] = ()
    missing_strategy: str = "drop"
    missing_options: Mapping[str, Any] = field(default_factory=dict)
    split: Mapping[str, Any] = field(default_factory=lambda: {"kind": "chronological", "train_fraction": 0.8})
    validation: Mapping[str, Any] = field(default_factory=lambda: {"kind": "holdout"})
    frequency: str | None = None
    alignment: Mapping[str, Any] = field(default_factory=lambda: {"kind": "exact_economic_time"})
    knowledge_cutoff: str | None = None
    release_binding: Mapping[str, Any] = field(default_factory=dict)
    label_definition: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.shape not in SUPPORTED_SHAPES:
            raise ModelingError("unsupported_input_shape", self.shape)
        if not self.y:
            raise ModelingError("missing_target", "at least one Y variable is required")
        if any(variable.role != "Y" for variable in self.y) or any(variable.role != "X" for variable in self.x):
            raise ModelingError("invalid_variable_role", "Y variables must have role Y and X variables must have role X")
        names = [variable.name for variable in (*self.y, *self.x)]
        if len(names) != len(set(names)):
            raise ModelingError("duplicate_variable_name", "Y and X variable names must be unique")
        if self.missing_strategy not in SUPPORTED_MISSING:
            raise ModelingError("unsupported_missing_strategy", self.missing_strategy)
        if self.missing_strategy == "forward_fill" and int(self.missing_options.get("max_age_days", 0)) < 1:
            raise ModelingError("forward_fill_staleness_unbounded", "forward fill requires a positive max_age_days contract")
        if self.horizon < 0:
            raise ModelingError("invalid_horizon", "horizon must be non-negative")
        if self.shape == "univariate_time_series" and len(self.y) != 1:
            raise ModelingError("invalid_y_cardinality", "univariate time series requires one Y")
        if self.shape == "supervised" and len(self.y) != 1:
            raise ModelingError("invalid_y_cardinality", "supervised models require one Y")
        if self.shape == "panel" and len(self.y) != 1:
            raise ModelingError("invalid_y_cardinality", "panel models require one Y")
        if self.shape == "panel" and not self.x:
            raise ModelingError("missing_panel_regressors", "panel models require at least one X")
        if self.split.get("kind", "chronological") != "chronological":
            raise ModelingError("unsupported_modeling_split", "Stage 1 supports chronological date-block splits only")
        if self.validation.get("kind", "holdout") != "holdout":
            raise ModelingError("unsupported_modeling_validation", "Stage 1 supports chronological holdout validation only")
        if self.alignment.get("kind", "exact_economic_time") != "exact_economic_time":
            raise ModelingError("unsupported_modeling_alignment", "Stage 1 requires exact economic-time alignment")

    def as_dict(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, "y": [v.as_dict() for v in self.y],
                "x": [v.as_dict() for v in self.x], "start": self.start, "end": self.end,
                "shape": self.shape, "horizon": self.horizon,
                "time_features": [dict(x) for x in self.time_features],
                "missing_strategy": self.missing_strategy, "missing_options": dict(self.missing_options), "split": dict(self.split),
                "validation": dict(self.validation), "knowledge_cutoff": self.knowledge_cutoff,
                "frequency": self.frequency, "alignment": dict(self.alignment),
                "release_binding": dict(self.release_binding), "label_definition": dict(self.label_definition)}


def _date_key(value: Any) -> str:
    text = str(value)
    if len(text) < 10:
        raise ModelingError("invalid_observation_time", f"invalid observation date: {value}")
    return text[:10]


def _numeric(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ModelingError("non_numeric_observation", f"non-numeric modeling value: {value!r}") from exc
    if not math.isfinite(result):
        raise ModelingError("non_finite_observation", "modeling values must be finite or missing")
    return result


def _chronological_train_end(dates: Sequence[str], train_fraction: float) -> int:
    """Return a split at a complete economic-time block.

    Panel rows are date-major, so splitting by raw row count can put entities
    from one date on opposite sides of the train/test boundary.  The boundary
    is selected from unique dates for every shape; for a non-panel series this
    is equivalent to the ordinary chronological split.
    """
    unique_dates = list(dict.fromkeys(dates))
    if len(unique_dates) < 2:
        raise ModelingError("insufficient_time_blocks", "chronological modeling requires at least two economic-time blocks")
    train_blocks = max(1, min(len(unique_dates) - 1, int(len(unique_dates) * train_fraction)))
    cutoff = unique_dates[train_blocks]
    return next((index for index, value in enumerate(dates) if value == cutoff), len(dates) - 1)


def _apply_transforms(values: np.ndarray, dates: list[str], operations: Sequence[Mapping[str, Any]]) -> np.ndarray:
    result = values.astype(float, copy=True)
    for operation in operations:
        name = str(operation.get("name", "raw"))
        if name == "raw":
            continue
        if name == "percentage_return":
            previous = np.roll(result, 1); result = result / previous - 1.0; result[0] = np.nan
        elif name == "log_return":
            if np.any(result <= 0): raise ModelingError("invalid_log_transform", "log return requires positive values")
            previous = np.roll(result, 1); result = np.log(result) - np.log(previous); result[0] = np.nan
        elif name == "first_difference":
            result = np.diff(result, prepend=np.nan)
        elif name == "log":
            if np.any(result <= 0): raise ModelingError("invalid_log_transform", "log requires positive values")
            result = np.log(result)
        elif name == "lag":
            n = int(operation.get("periods", operation.get("n", 1)))
            if n < 1: raise ModelingError("invalid_lag", "lag periods must be positive")
            result = np.concatenate([np.full(n, np.nan), result[:-n]])
        elif name in {"rolling_mean", "rolling_volatility"}:
            window = int(operation.get("window", 20))
            if window < 2: raise ModelingError("invalid_rolling_window", "rolling window must be >= 2")
            out = np.full(len(result), np.nan)
            for i in range(window - 1, len(result)):
                sample = result[i - window + 1:i + 1]
                if np.all(np.isfinite(sample)):
                    out[i] = np.mean(sample) if name == "rolling_mean" else np.std(sample, ddof=1)
            result = out
        elif name == "standardize":
            finite = result[np.isfinite(result)]
            if not len(finite) or np.std(finite) == 0: raise ModelingError("invalid_standardization", "cannot standardize constant/empty variable")
            result = (result - np.mean(finite)) / np.std(finite, ddof=1)
    return result


def _model_space_unit(variable: Mapping[str, Any], source_representation: Any) -> str | Any:
    """Describe the target space without pretending it is the source unit."""
    operations = [str(op.get("name", "raw")) for op in variable.get("transformations", [])]
    if not operations or operations == ["raw"]:
        return source_representation
    if operations[-1] == "standardize":
        return "training_standard_score"
    unit = source_representation
    for operation in operations:
        if operation == "percentage_return": unit = "decimal_percentage_change"
        elif operation == "log_return": unit = "log_change"
        elif operation == "first_difference": unit = "first_difference_of(" + str(unit) + ")"
        elif operation == "log": unit = "log_of(" + str(unit) + ")"
        elif operation == "lag": unit = "lagged(" + str(unit) + ")"
        elif operation == "rolling_mean": unit = "rolling_mean_of(" + str(unit) + ")"
        elif operation == "rolling_volatility": unit = "rolling_volatility_of(" + str(unit) + ")"
    return unit


def _time_features(dates: list[str], definitions: Sequence[Mapping[str, Any]]) -> dict[str, np.ndarray]:
    import datetime as dt
    parsed = [dt.date.fromisoformat(x) for x in dates]
    date_ordinals = {value: index for index, value in enumerate(dict.fromkeys(dates))}
    result: dict[str, np.ndarray] = {}
    for definition in definitions:
        name = str(definition.get("name"))
        if name == "linear_trend": result[name] = np.array([date_ordinals[d] for d in dates], dtype=float)
        elif name == "weekday": result[name] = np.array([d.weekday() for d in parsed], dtype=float)
        elif name == "month": result[name] = np.array([d.month for d in parsed], dtype=float)
        elif name == "quarter": result[name] = np.array([(d.month - 1) // 3 + 1 for d in parsed], dtype=float)
        elif name == "trading_day_sequence": result[name] = np.array([date_ordinals[d] for d in dates], dtype=float)
        elif name in {"weekday_dummies", "month_dummies", "quarter_dummies", "group_dummies"}:
            if name == "weekday_dummies": values = np.array([d.weekday() for d in parsed]); count = 7
            elif name == "month_dummies": values = np.array([d.month for d in parsed]); count = 12
            elif name == "quarter_dummies": values = np.array([(d.month - 1) // 3 + 1 for d in parsed]); count = 4
            else:
                groups = list(definition.get("groups") or [])
                values = np.array([next((int(g["value"]) for g in groups if d.isoformat() >= str(g["start"]) and d.isoformat() <= str(g["end"])), -1) for d in parsed]); count = int(definition.get("count", max(values, default=0) + 1))
            reference = int(definition.get("reference", 0))
            for category in range(count):
                if category != reference: result[f"{name}_{category}"] = (values == category).astype(float)
        else:
            raise ModelingError("unsupported_time_feature", name)
    return result


def _missing(values: np.ndarray, strategy: str, *, train_end: int, target_count: int = 0,
             dates: Sequence[str] | None = None, max_age_days: int | None = None) -> np.ndarray:
    result = values.astype(float, copy=True)
    if strategy == "drop": return result
    # Missing target values are never financial observations and cannot be filled.
    for col in range(target_count, result.shape[1]):
        series = result[:, col]
        if strategy == "forward_fill":
            last = np.nan
            last_date = None
            for i, value in enumerate(series):
                if np.isfinite(value):
                    last = value
                    last_date = dates[i] if dates else None
                elif np.isfinite(last) and dates and last_date and max_age_days is not None:
                    age = (datetime.fromisoformat(dates[i]).date() - datetime.fromisoformat(last_date).date()).days
                    if 0 <= age <= max_age_days:
                        series[i] = last
        elif strategy == "backward_fill":
            nxt = np.nan
            # Backward filling from the test partition would use future
            # information.  Only the training boundary may be fitted here.
            for i in range(train_end - 1, -1, -1):
                if np.isfinite(series[i]): nxt = series[i]
                elif np.isfinite(nxt): series[i] = nxt
        elif strategy == "linear":
            good = np.flatnonzero(np.isfinite(series[:train_end]))
            if len(good) >= 2: series[:train_end] = np.interp(np.arange(train_end), good, series[:train_end][good])
        elif strategy in {"mean", "median"}:
            good = series[:train_end][np.isfinite(series[:train_end])]
            if len(good): series[~np.isfinite(series)] = np.mean(good) if strategy == "mean" else np.median(good)
    return result


def _fit_fold_preprocessing(raw: np.ndarray, spec: Mapping[str, Any], columns: Sequence[str],
                            train_end: int) -> tuple[np.ndarray, dict[str, Any], dict[str, int] | None, dict[str, Any]]:
    """Fit learned transforms on this fold's training rows, then apply them to its evaluation rows."""
    values = raw.astype(float, copy=True)
    y_count = len(spec["y"])
    strategy = str(spec["missing_strategy"])
    learned: dict[str, Any] = {"imputation": {}, "standardization": {}}
    if strategy in {"mean", "median"}:
        for col in range(y_count, values.shape[1]):
            good = values[:train_end, col][np.isfinite(values[:train_end, col])]
            if not len(good):
                raise ModelingError("unlearnable_feature_imputation", f"{columns[col]} has no training observations")
            replacement = float(np.mean(good) if strategy == "mean" else np.median(good))
            values[~np.isfinite(values[:, col]), col] = replacement
            learned["imputation"][columns[col]] = replacement
    if not np.all(np.isfinite(values)):
        raise ModelingError("unresolved_modeling_missingness", "target or feature remains missing after the declared policy")
    for variable in (*spec["y"], *spec["x"]):
        if any(str(op.get("name", "raw")) == "standardize" for op in variable.get("transformations", [])):
            col = columns.index(variable["name"])
            training = values[:train_end, col]
            mean, std = float(np.mean(training)), float(np.std(training, ddof=1))
            if not np.isfinite(std) or std == 0:
                raise ModelingError("invalid_standardization", f"cannot standardize {variable['name']}")
            values[:, col] = (values[:, col] - mean) / std
            learned["standardization"][variable["name"]] = {"mean": mean, "std": std}
    label_definition = dict(spec.get("label_definition") or {})
    counts = None
    if label_definition:
        target_index = columns.index(spec["y"][0]["name"])
        target = values[:, target_index].copy()
        kind = str(label_definition.get("kind", ""))
        if kind == "binary_threshold":
            values[:, target_index] = (target >= float(label_definition["threshold"])).astype(float)
        elif kind == "intervals":
            labels = np.full(len(target), np.nan)
            for interval in label_definition.get("intervals") or []:
                labels[(target >= float(interval["lower"])) & (target < float(interval["upper"]))] = float(interval["label"])
            if not np.all(np.isfinite(labels)):
                raise ModelingError("unlabeled_target", "classification intervals must cover every retained target")
            values[:, target_index] = labels
        elif kind == "quantile_classes":
            count = int(label_definition.get("count", 2))
            if count < 2:
                raise ModelingError("invalid_quantile_classes", "at least two classes are required")
            edges = np.quantile(target[:train_end], np.linspace(0, 1, count + 1))
            if len(set(edges.tolist())) != len(edges):
                raise ModelingError("degenerate_quantile_classes", "training quantiles do not separate classes")
            values[:, target_index] = np.digitize(target, edges[1:-1]).astype(float)
            label_definition["train_quantile_edges"] = [float(edge) for edge in edges]
        else:
            raise ModelingError("unsupported_label_definition", kind)
        labels = values[:, target_index]
        counts = {str(int(key)): int(np.sum(labels == key)) for key in sorted(set(labels.tolist()))}
    return values, label_definition, counts, learned


def build_dataset(spec: ModelingDatasetSpec, observations: Mapping[str, Sequence[Mapping[str, Any]]], *, input_metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build a deterministic preview/frozen input from already release-bound points."""
    if spec.shape != "supervised" and spec.horizon:
        raise ModelingError("model_native_horizon_required", "time-series and panel estimators do not pre-shift Y; forecast horizon belongs to the estimator task")
    if spec.missing_strategy in {"backward_fill", "linear"}:
        raise ModelingError("predictive_lookahead_policy", "backward fill and bidirectional interpolation are unavailable for evaluated Modeling inputs")
    keys = [v.series_key for v in (*spec.y, *spec.x)]
    if len(set(keys)) != len(keys): raise ModelingError("duplicate_series_selection", "each Series may be selected once")
    by_key: dict[str, dict[Any, float]] = {}
    representation: dict[str, set[tuple[str, str, str]]] = {}
    time_roles: dict[str, set[str]] = {}
    all_dates: set[str] = set()
    panel_keys: set[tuple[str, str]] = set()
    panel_entities: list[str] = []
    panel_listings: list[str | None] = []
    panel_listing_by_key: dict[tuple[str, str], str | None] = {}
    accepted_time_roles = dict((input_metadata or {}).get("accepted_time_roles", {}))
    for key in keys:
        rows = observations.get(key)
        if rows is None: raise ModelingError("series_not_returned", key)
        by_key[key] = {}
        representation[key] = set()
        time_roles[key] = set()
        for row in rows:
            date_key = _date_key(row.get("economic_time"))
            if spec.start and date_key < spec.start or spec.end and date_key > spec.end: continue
            role = row.get("time_role")
            if role is not None:
                time_roles[key].add(str(role))
            if input_metadata and input_metadata.get("release_id"):
                allowed_roles = set(accepted_time_roles.get(key) or ("observation_date",))
                if role not in allowed_roles:
                    raise ModelingError(
                        "unsupported_modeling_time_role",
                        f"{key} requires one of the accepted modeling time roles: {', '.join(sorted(allowed_roles))}",
                        422,
                    )
            representation[key].add((str(row.get("unit")), str(row.get("currency")), str(row.get("scale"))))
            if len(representation[key]) > 1:
                raise ModelingError("mixed_financial_representation", f"{key} changes unit, currency or scale within one Modeling input", 422)
            availability = row.get("availability_time") or row.get("known_at") or row.get("as_known_at")
            if availability is None and role in {"observation_date", "nav_date"}:
                availability = date_key
            if spec.horizon and key in {variable.series_key for variable in spec.x} and availability is not None and _date_key(availability) > date_key:
                raise ModelingError("future_feature_at_origin", f"{key} was not available at its prediction origin", 422)
            if spec.knowledge_cutoff:
                if availability is None:
                    raise ModelingError("availability_time_unproven", f"{key} has no proved availability time for knowledge_cutoff")
                if _date_key(availability) > _date_key(spec.knowledge_cutoff):
                    continue
            if spec.shape == "panel":
                entity = row.get("entity_id", row.get("entity"))
                if entity is None or str(entity) == "": raise ModelingError("missing_panel_identity", "panel observations require entity_id")
                panel_key = (str(entity), date_key)
                if panel_key in by_key[key]: raise ModelingError("duplicate_panel_observation", key)
                by_key[key][panel_key] = _numeric(row.get("value")); panel_keys.add(panel_key); all_dates.add(date_key)
                listing_id = str(row.get("listing_id") or "") or None
                if panel_key in panel_listing_by_key and panel_listing_by_key[panel_key] != listing_id:
                    raise ModelingError("ambiguous_panel_identity", f"{key} maps one entity/date to multiple listing identities", 422)
                panel_listing_by_key[panel_key] = listing_id
            else:
                if date_key in by_key[key]: raise ModelingError("duplicate_observation_date", key)
                by_key[key][date_key] = _numeric(row.get("value")); all_dates.add(date_key)
    # Panel rows are ordered by economic time first so chronological splits
    # hold out later dates for every entity rather than training on one entity
    # and testing on another.
    ordered_panel_keys = sorted(panel_keys, key=lambda item: (item[1], item[0]))
    if spec.shape == "panel":
        dates = [item[1] for item in ordered_panel_keys]
        panel_entities = [item[0] for item in ordered_panel_keys]
        panel_listings = [panel_listing_by_key.get(item) for item in ordered_panel_keys]
    else:
        dates = sorted(all_dates)
    matrix: dict[str, np.ndarray] = {}
    source_matrix: dict[str, np.ndarray] = {}
    for variable in (*spec.y, *spec.x):
        lookup_keys = ordered_panel_keys if spec.shape == "panel" else dates
        raw = np.array([by_key[variable.series_key].get(day, np.nan) for day in lookup_keys], dtype=float)
        source_matrix[variable.name] = raw.copy()
        # Standardization is fitted after the chronological boundary is known;
        # applying it here would leak test statistics into the training input.
        operations = [op for op in variable.transformations if str(op.get("name", "raw")) != "standardize"]
        if spec.shape == "panel" and operations:
            transformed = np.full(len(raw), np.nan)
            for entity in sorted(set(panel_entities)):
                indices = [i for i, value in enumerate(panel_entities) if value == entity]
                transformed[indices] = _apply_transforms(raw[indices], [dates[i] for i in indices], operations)
            matrix[variable.name] = transformed
        else:
            matrix[variable.name] = _apply_transforms(raw, dates, operations)
    for name, values in _time_features(dates, spec.time_features).items(): matrix[name] = values
    columns = [v.name for v in spec.y] + [v.name for v in spec.x] + list(_time_features(dates, spec.time_features).keys())
    target_names = [v.name for v in spec.y]
    target_dates = list(dates)
    if spec.horizon:
        if spec.shape != "supervised":
            raise ModelingError("invalid_supervised_horizon", "Y shifting is only a supervised prediction operation")
        target_dates = dates[spec.horizon:] + [None] * spec.horizon
        for target in target_names:
            shifted = np.full(len(dates), np.nan)
            if spec.shape == "panel":
                for entity in sorted(set(panel_entities)):
                    indices = [i for i, value in enumerate(panel_entities) if value == entity]
                    if len(indices) > spec.horizon:
                        shifted[indices[:-spec.horizon]] = matrix[target][indices[spec.horizon:]]
            else:
                shifted[:-spec.horizon] = matrix[target][spec.horizon:]
            matrix[target] = shifted
    values = np.column_stack([matrix[col] for col in columns]) if columns else np.empty((len(dates), 0))
    before_missing = int(np.sum(np.any(~np.isfinite(values), axis=1)))
    preliminary_train_end = _chronological_train_end(dates, float(spec.split.get("train_fraction", 0.8)))
    if spec.shape == "panel" and spec.missing_strategy == "forward_fill":
        # Forward/backward filling and train-fitted imputation must never use
        # another entity's rows as its history.
        filled = values.copy()
        for entity in sorted(set(panel_entities)):
            indices = [i for i, value in enumerate(panel_entities) if value == entity]
            entity_train_end = sum(i < preliminary_train_end for i in indices)
            filled[indices] = _missing(values[indices], spec.missing_strategy, train_end=entity_train_end,
                                       target_count=len(target_names), dates=[dates[i] for i in indices],
                                       max_age_days=int(spec.missing_options["max_age_days"]))
        values = filled
    elif spec.missing_strategy == "forward_fill":
        values = _missing(values, spec.missing_strategy, train_end=preliminary_train_end,
                          target_count=len(target_names), dates=dates,
                          max_age_days=int(spec.missing_options["max_age_days"]))
    # Mean/median feature imputers are learned below, after the exact split and
    # any horizon purge have been established. Never impute a target.
    keep = np.all(np.isfinite(values[:, :len(target_names)]), axis=1)
    if spec.missing_strategy in {"drop", "forward_fill"}:
        keep &= np.all(np.isfinite(values[:, len(target_names):]), axis=1)
    dates = [day for day, flag in zip(dates, keep) if flag]
    target_dates = [day for day, flag in zip(target_dates, keep) if flag]
    values = values[keep]
    source_matrix = {name: raw[keep] for name, raw in source_matrix.items()}
    if spec.shape == "panel":
        # Entity identity is row-aligned metadata and must follow every row
        # filtering operation exactly.
        panel_entities = [entity for entity, flag in zip(panel_entities, keep) if flag]
        panel_listings = [listing for listing, flag in zip(panel_listings, keep) if flag]
    if len(values) < 2: raise ModelingError("insufficient_modeling_rows", "fewer than two usable rows remain after preparation")
    split = dict(spec.split); kind = str(split.get("kind", "chronological")); train_fraction = float(split.get("train_fraction", 0.8))
    if not 0.5 <= train_fraction < 1: raise ModelingError("invalid_split", "train_fraction must be in [0.5, 1)")
    train_end = _chronological_train_end(dates, train_fraction)
    outer_test_date = dates[train_end]
    purged = [i for i in range(train_end) if target_dates[i] is not None and target_dates[i] >= outer_test_date]
    if purged:
        retained = [i for i in range(len(dates)) if i not in set(purged)]
        values = values[retained]
        source_matrix = {name: raw[retained] for name, raw in source_matrix.items()}
        dates = [dates[i] for i in retained]
        target_dates = [target_dates[i] for i in retained]
        if spec.shape == "panel": panel_entities = [panel_entities[i] for i in retained]
        if spec.shape == "panel": panel_listings = [panel_listings[i] for i in retained]
        train_end -= len(purged)
    if train_end < 2 or train_end == len(values):
        raise ModelingError("insufficient_training_or_test_rows", "the temporal split and target gap leave insufficient rows")
    raw_values = values.copy()
    values, label_definition, class_counts, learned = _fit_fold_preprocessing(raw_values, spec.as_dict(), columns, train_end)
    target_contract = {}
    declared_chain = []
    for variable in (*spec.y, *spec.x):
        chain = [dict(operation) for operation in variable.transformations]
        declared_chain.append({"variable": variable.name, "series_key": variable.series_key,
                               "role": variable.role, "steps": chain})
        source_repr = [list(item) for item in sorted(representation.get(variable.series_key, set()))]
        target_contract[variable.name] = {
            "series_key": variable.series_key,
            "source_representation": source_repr,
            "model_space_unit": _model_space_unit(variable.as_dict(), source_repr),
            "transformation_steps": chain,
        }
    transformation_contract = {
        "declared_chain": declared_chain,
        "effective_chain": declared_chain,
        "learned_steps": learned.get("standardization", {}),
    }
    transformation_contract["chain_digest"] = digest(transformation_contract)
    partitions = {"train": [0, train_end], "test": [train_end, len(values)], "kind": kind}
    payload = {"schema_version": DATASET_SCHEMA_VERSION, "columns": columns, "y_columns": target_names,
               "x_columns": [v.name for v in spec.x] + list(_time_features(dates, spec.time_features).keys()),
                "dates": dates, "target_dates": target_dates, "values": values.tolist(),
                "raw_values": raw_values.tolist(), "row_count": len(values),
                "source_values": {name: raw.tolist() for name, raw in source_matrix.items()},
                "source_time_roles": {key: sorted(roles) for key, roles in time_roles.items()},
                "source_representation": {key: [list(item) for item in sorted(values)] for key, values in representation.items()},
               "raw_row_count": len(panel_keys) if spec.shape == "panel" else len(all_dates), "rows_with_missing_before_policy": before_missing,
               "missing_strategy": spec.missing_strategy, "partitions": partitions,
               "shape": spec.shape, "horizon": spec.horizon, "spec": spec.as_dict(),
               "input_metadata": dict(input_metadata or {}), "label_definition": label_definition,
                "class_counts": class_counts, "learned_preprocessing": learned,
                "transformation_contract": transformation_contract,
                "target_contract": target_contract,
                "purged_outer_train_rows": len(purged),
                "information_state": "latest_revised_observation_date_not_as_known_revision_replay"}
    if spec.shape == "panel":
        payload["entity_ids"] = panel_entities
        payload["listing_ids"] = panel_listings
    payload["input_digest"] = digest(payload)
    return payload


def _split_xy(dataset: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    values = np.asarray(dataset["values"], dtype=float); y_count = len(dataset["y_columns"])
    train_end = int(dataset["partitions"]["train"][1]); return values[:train_end, y_count:], values[:train_end, :y_count], values[train_end:, y_count:], values[train_end:, :y_count]


def _ols(x: np.ndarray, y: np.ndarray, ridge: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    design = np.column_stack([np.ones(len(x)), x]); penalty = np.eye(design.shape[1]); penalty[0, 0] = 0
    if ridge < 0: raise ModelingError("invalid_ridge_penalty", "ridge alpha must be nonnegative")
    if ridge == 0:
        coef, _, rank, _ = np.linalg.lstsq(design, y, rcond=None)
        if rank != design.shape[1]:
            raise ModelingError("rank_deficient_design", "OLS design is not identified")
    else:
        coef = np.linalg.solve(design.T @ design + ridge * penalty, design.T @ y)
    fitted = design @ coef
    return coef, fitted


def _logistic(x: np.ndarray, y: np.ndarray, iterations: int = 3000, learning_rate: float = 0.05) -> tuple[np.ndarray, np.ndarray]:
    design = np.column_stack([np.ones(len(x)), x]); weights = np.zeros(design.shape[1])
    for _ in range(iterations):
        scores = np.clip(design @ weights, -40, 40); probabilities = 1 / (1 + np.exp(-scores)); weights -= learning_rate * (design.T @ (probabilities - y)) / len(y)
    probabilities = 1 / (1 + np.exp(-(design @ weights))); return weights, probabilities



def _statsmodels_available() -> bool:
    return bool(importlib.util.find_spec("statsmodels"))


def _forecast_result(result: Any, steps: int) -> np.ndarray:
    if not steps:
        return np.array([], dtype=float)
    forecast = result.forecast(steps=steps)
    return np.asarray(forecast, dtype=float).reshape(-1)[:steps]


def _fit_optional_model(model_id: str, dataset: Mapping[str, Any], parameters: Mapping[str, Any], x_train: np.ndarray, y_train: np.ndarray, x_test: np.ndarray, y_test: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    """Adapter boundary for mature libraries; imports stay optional and local."""
    steps = int(parameters.get("forecast_steps", len(y_test)))
    if model_id in {"wls", "gls"}:
        import statsmodels.api as sm
        design = sm.add_constant(x_train, has_constant="add")
        test_design = sm.add_constant(x_test, has_constant="add")
        if model_id == "wls":
            weights = np.asarray(parameters["weights"], dtype=float)
            if len(weights) != len(y_train) or np.any(weights <= 0): raise ModelingError("invalid_model_weights", "WLS weights must match training rows and be positive")
            result = sm.WLS(y_train, design, weights=weights).fit()
        else:
            sigma = parameters.get("sigma")
            if sigma is None:
                raise ModelingError("missing_gls_covariance", "GLS requires an explicit sigma covariance matrix", 422)
            sigma = np.asarray(sigma, dtype=float)
            if sigma.shape != (len(y_train), len(y_train)) or not np.all(np.isfinite(sigma)) or not np.allclose(sigma, sigma.T) or np.min(np.linalg.eigvalsh(sigma)) <= 0:
                raise ModelingError("invalid_gls_covariance", "GLS sigma must be a finite square matrix matching training rows", 422)
            result = sm.GLS(y_train, design, sigma=sigma).fit()
        return np.asarray(result.predict(test_design), dtype=float), {"coefficients": result.params.tolist(), "aic": float(result.aic), "bic": float(result.bic), "covariance_weighted": model_id == "gls", "weight_basis": parameters.get("weights_basis"), "covariance_basis": parameters.get("sigma_basis"), "standard_errors": result.bse.tolist(), "p_values": result.pvalues.tolist()}
    if model_id in {"ar", "ma", "arma", "arima", "sarima", "sarimax", "exponential_smoothing", "holt", "holt_winters"}:
        from statsmodels.tsa.arima.model import ARIMA
        if model_id in {"ar", "ma", "arma", "arima", "sarima", "sarimax"}:
            defaults = {"ar": (1, 0, 0), "ma": (0, 0, 1), "arma": (1, 0, 1), "arima": (1, 0, 0), "sarima": (1, 0, 0), "sarimax": (1, 0, 0)}
            order = tuple(parameters.get("order", defaults[model_id]))
            seasonal_order = tuple(parameters.get("seasonal_order", (0, 0, 0, 0))) if model_id in {"sarima", "sarimax"} else (0, 0, 0, 0)
            has_exog = model_id == "sarimax" and bool(dataset.get("x_columns")) and x_train.shape[1]
            exog_train = x_train if has_exog else None
            exog_test = np.asarray(parameters["future_exog_contract"]["values"], dtype=float) if has_exog else None
            if has_exog and (exog_test.shape != (steps, x_test.shape[1]) or not np.all(np.isfinite(exog_test))):
                raise ModelingError("invalid_future_exog", "scenario X must match the forecast rows and regressors", 422)
            result = ARIMA(y_train, order=order, seasonal_order=seasonal_order, exog=exog_train).fit()
            if result.mle_retvals.get("converged") is False:
                raise ModelingError("model_nonconvergence", f"{model_id} likelihood optimization did not converge", 422)
            prediction = result.forecast(steps=steps, exog=exog_test) if steps else np.array([], dtype=float)
            return np.asarray(prediction, dtype=float).reshape(-1), {"order": list(order), "seasonal_order": list(seasonal_order), "aic": float(result.aic), "bic": float(result.bic), "forecast_kind": "conditional_scenario_mean" if has_exog else "conditional_mean", "future_exog_basis": parameters.get("future_exog_contract", {}).get("basis")}
        from statsmodels.tsa.holtwinters import ExponentialSmoothing, Holt, SimpleExpSmoothing
        if model_id == "exponential_smoothing":
            result = SimpleExpSmoothing(y_train, initialization_method="estimated").fit(optimized=True)
        elif model_id == "holt":
            result = Holt(y_train, initialization_method="estimated").fit(optimized=True)
        else:
            trend = parameters.get("trend", "add"); seasonal = parameters.get("seasonal", "add"); period = int(parameters.get("seasonal_periods", 12))
            result = ExponentialSmoothing(y_train, trend=trend, seasonal=seasonal, seasonal_periods=period).fit(optimized=True)
        return _forecast_result(result, steps), {"aic": float(getattr(result, "aic", float("nan")))}
    if model_id in {"var", "vecm"}:
        if dataset["shape"] != "multivariate_time_series": raise ModelingError("invalid_multivariate_shape", f"{model_id} requires multivariate_time_series")
        y_count = len(dataset["y_columns"]); all_values = np.asarray(dataset["values"], dtype=float); full_train = all_values[:dataset["partitions"]["train"][1], :y_count]
        if full_train.shape[1] < 2: raise ModelingError("insufficient_multivariate_series", f"{model_id} requires at least two Y variables")
        if model_id == "var":
            from statsmodels.tsa.api import VAR
            result = VAR(full_train).fit(maxlags=parameters.get("lags"), trend=parameters.get("trend", "c"))
            forecast = result.forecast(full_train[-result.k_ar:], steps=steps) if steps else np.empty((0, full_train.shape[1]))
        else:
            from statsmodels.tsa.vector_ar.vecm import VECM
            result = VECM(full_train, k_ar_diff=int(parameters.get("k_ar_diff", 1)), coint_rank=int(parameters.get("coint_rank", 1)), deterministic=parameters.get("deterministic", "n")).fit()
            forecast = result.predict(steps=steps) if steps else np.empty((0, full_train.shape[1]))
        details = {"forecast_columns": list(dataset["y_columns"]), "forecast": np.asarray(forecast).tolist(), "forecast_kind": "vector_conditional_mean"}
        if model_id == "vecm":
            details.update({"cointegration_rank": int(result.coint_rank), "rank_basis": parameters["rank_basis"],
                            "alpha": result.alpha.tolist(), "beta": result.beta.tolist(),
                            "deterministic": parameters.get("deterministic", "n")})
        else:
            details.update({"lag_order": int(result.k_ar), "stability": bool(result.is_stable())})
        return np.asarray(forecast, dtype=float), details
    if model_id in {"markov_regression", "markov_autoregression", "unobserved_components"}:
        if model_id == "markov_regression":
            from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression
            result = MarkovRegression(y_train, k_regimes=int(parameters.get("k_regimes", 2)), trend=str(parameters.get("trend", "c")), switching_variance=bool(parameters.get("switching_variance", False))).fit(disp=False, maxiter=int(parameters.get("maxiter", 200)))
        elif model_id == "markov_autoregression":
            from statsmodels.tsa.regime_switching.markov_autoregression import MarkovAutoregression
            # A switching variance is a materially different model and is
            # numerically fragile for short financial samples.  Keep the
            # default contract stationary and explicit; callers may opt in.
            model = MarkovAutoregression(
                y_train,
                k_regimes=int(parameters.get("k_regimes", 2)),
                order=int(parameters.get("order", 1)),
                trend=str(parameters.get("trend", "c")),
                switching_variance=bool(parameters.get("switching_variance", False)),
            )
            result = model.fit(disp=False, maxiter=int(parameters.get("maxiter", 200)))
        else:
            from statsmodels.tsa.statespace.structural import UnobservedComponents
            model = UnobservedComponents(y_train, level=parameters.get("level", "local linear trend"))
            result = model.fit(disp=False)
        if getattr(result, "mle_retvals", {}).get("converged") is False:
            raise ModelingError("model_nonconvergence", f"{model_id} likelihood optimization did not converge", 422)
        # FR deliberately exposes no unvalidated Markov forecast contract.
        if steps:
            if model_id == "markov_autoregression":
                prediction = np.array([], dtype=float)
            elif model_id == "markov_regression":
                prediction = np.array([], dtype=float)
            else:
                forecast = result.get_forecast(steps=steps)
                prediction = np.asarray(forecast.predicted_mean, dtype=float).reshape(-1)[:steps]
        else:
            prediction = np.array([], dtype=float)
        probabilities = getattr(result, "smoothed_marginal_probabilities", None)
        filtered = getattr(result, "filtered_marginal_probabilities", None)
        transition = getattr(result, "regime_transition", None)
        state_count = len(probabilities) if probabilities is not None else len(y_train)
        return np.asarray(prediction, dtype=float).reshape(-1), {
            "aic": float(getattr(result, "aic", float("nan"))),
            "smoothed_state_probabilities": probabilities.tolist() if probabilities is not None else None,
            "filtered_state_probabilities": filtered.tolist() if filtered is not None else None,
            "regime_transition": np.asarray(transition).tolist() if transition is not None else None,
            "state_dates": list(dataset["dates"][:dataset["partitions"]["train"][1]])[-state_count:],
            "state_parameters": np.asarray(result.params).tolist(),
            "state_estimates": (result.filtered_state.tolist() if model_id not in {"markov_regression", "markov_autoregression"} else None),
            "forecast_available": model_id not in {"markov_regression", "markov_autoregression"},
            "forecast_kind": "model_state_forecast" if model_id not in {"markov_regression", "markov_autoregression"} else None,
        }
    if model_id in {"arch", "garch", "egarch", "gjr_tarch", "aparch"}:
        from arch import arch_model
        from arch.univariate import APARCH
        vol = {"arch": "ARCH", "garch": "GARCH", "egarch": "EGARCH", "gjr_tarch": "GARCH", "aparch": "APARCH"}[model_id]
        power = float(parameters.get("power", 2.0))
        if "power" in parameters and (model_id != "gjr_tarch" or power not in {1.0, 2.0}):
            raise ModelingError("invalid_volatility_power", "GJR/TARCH supports power 2 or 1 respectively", 422)
        scale_factor = 100.0
        process = arch_model(y_train * scale_factor, mean=parameters.get("mean", "Constant"), vol=vol,
                            p=int(parameters.get("p", 1)), o=int(parameters.get("o", 1 if model_id == "gjr_tarch" else 0)),
                            q=int(parameters.get("q", 1)), power=power,
                            dist=parameters.get("distribution", "normal"), rescale=False)
        if model_id == "aparch":
            # arch_model's power argument does not set APARCH delta. Use the
            # volatility process directly so a supplied delta is truly fixed.
            process.volatility = APARCH(p=int(parameters.get("p", 1)), o=int(parameters.get("o", 0)),
                                        q=int(parameters.get("q", 1)), delta=parameters.get("delta"))
        result = process.fit(disp="off")
        if getattr(result, "convergence_flag", 0) != 0:
            raise ModelingError("model_nonconvergence", f"{model_id} volatility optimization did not converge", 422)
        method = ("analytic" if model_id in {"arch", "garch", "gjr_tarch"} and steps <= 1
                  and not ({"simulations", "seed"} & set(parameters)) else "simulation")
        forecast_kwargs = {"horizon": max(1, steps), "method": method,
                           "simulations": int(parameters.get("simulations", 200))}
        if method == "simulation":
            forecast_kwargs["rng"] = np.random.default_rng(int(parameters.get("seed", 0))).standard_normal
        forecast_result = result.forecast(**forecast_kwargs) if steps else None
        variance = forecast_result.residual_variance.iloc[-1].to_numpy() / scale_factor ** 2 if steps else np.array([], dtype=float)
        mean_forecast = forecast_result.mean.iloc[-1].to_numpy() / scale_factor if steps else np.array([], dtype=float)
        volatility = np.sqrt(np.maximum(variance, 0.0))
        return np.asarray(volatility, dtype=float)[:steps], {
            "volatility": vol, "forecast_kind": "conditional_volatility", "conditional_mean": np.asarray(mean_forecast).tolist(),
            "conditional_variance": np.asarray(variance, dtype=float)[:steps].tolist(),
            "conditional_volatility": np.asarray(volatility, dtype=float)[:steps].tolist(),
            "observation_variance": (forecast_result.variance.iloc[-1].to_numpy() / scale_factor ** 2).tolist() if steps else [],
            "distribution": parameters.get("distribution", "normal"), "mean_specification": parameters.get("mean", "Constant"),
            "input_return_unit": "log_change" if "log_return" in [op.get("name") for op in dataset.get("spec", {}).get("y", [{}])[0].get("transformations", [])] else "decimal_percentage_change",
            "fit_scale_factor": scale_factor,
            "power": power if model_id == "gjr_tarch" else None,
            "aparch_delta": (float(parameters["delta"]) if "delta" in parameters else float(result.params.get("delta", float("nan")))) if model_id == "aparch" else None,
            "aparch_delta_fixed": model_id == "aparch" and "delta" in parameters,
            "variant": "TARCH" if model_id == "gjr_tarch" and power == 1.0 else "GJR_GARCH" if model_id == "gjr_tarch" else vol,
            "p": int(parameters.get("p", 1)), "o": int(parameters.get("o", 1 if model_id == "gjr_tarch" else 0)),
            "q": int(parameters.get("q", 1)), "aic": float(result.aic), "bic": float(result.bic),
        }
    if model_id in {"pooled_ols", "fixed_effects", "random_effects", "first_difference", "fama_macbeth"}:
        import pandas as pd
        entities = dataset.get("entity_ids")
        if not entities or len(entities) != len(dataset["values"]): raise ModelingError("missing_panel_identity", "panel execution requires explicit entity_ids in the frozen dataset")
        y_count = len(dataset["y_columns"]); x_names = list(dataset["x_columns"])
        if not x_names: raise ModelingError("missing_panel_regressors", "panel execution requires at least one X variable")
        frame = pd.DataFrame(np.asarray(dataset["values"], dtype=float), columns=list(dataset["columns"]))
        frame["__entity"] = list(entities); frame["__time"] = pd.to_datetime(list(dataset["dates"])); frame = frame.set_index(["__entity", "__time"])
        from linearmodels.panel import FamaMacBeth, FirstDifferenceOLS, PanelOLS, PooledOLS, RandomEffects
        boundary = int(dataset["partitions"]["train"][1]); train_frame = frame.iloc[:boundary].sort_index(); raw_test_frame = frame.iloc[boundary:]; test_frame = raw_test_frame.sort_index()
        y = train_frame[dataset["y_columns"][0]]; exog = train_frame[x_names]
        classes = {"pooled_ols": PooledOLS, "fixed_effects": PanelOLS, "random_effects": RandomEffects, "first_difference": FirstDifferenceOLS, "fama_macbeth": FamaMacBeth}
        if model_id == "fixed_effects":
            entity_effects = bool(parameters.get("entity_effects", True))
            time_effects = bool(parameters.get("time_effects", False))
            if not entity_effects and not time_effects:
                raise ModelingError("invalid_fixed_effects_contract", "fixed_effects requires entity_effects or time_effects", 422)
            model = PanelOLS(y, exog, entity_effects=entity_effects, time_effects=time_effects, check_rank=True)
        else:
            model = classes[model_id](y, exog, check_rank=True)
        result = model.fit(cov_type=parameters.get("cov_type", "unadjusted"))
        if len(test_frame):
            if model_id == "first_difference" or (model_id == "fixed_effects" and time_effects):
                # Future date effects are unobserved by construction.  A fit
                # with time effects is valid, but it cannot claim a held-out
                # level forecast from exogenous terms alone.
                prediction = np.array([], dtype=float)
            else:
                predicted = result.predict(exog=test_frame[x_names])
                if model_id == "fixed_effects" and entity_effects:
                    known_effects = result.estimated_effects.iloc[:, 0].groupby(level=0).mean()
                    try:
                        entity_effect = np.asarray([known_effects.loc[entity] for entity in test_frame.index.get_level_values(0)], dtype=float)
                    except KeyError as exc:
                        raise ModelingError("unseen_panel_entity", "held-out entity has no fitted effect", 422) from exc
                    predicted = predicted.copy()
                    predicted.iloc[:, 0] = predicted.iloc[:, 0].to_numpy() + entity_effect
                prediction = np.asarray(predicted.reindex(raw_test_frame.index)).reshape(-1)
        else:
            prediction = np.array([], dtype=float)
        estimated_effects = getattr(result, "estimated_effects", None) if model_id in {"fixed_effects", "random_effects"} else None
        period_parameters = getattr(result, "all_params", None) if model_id == "fama_macbeth" else None
        return prediction, {"parameters": result.params.to_dict(), "rsquared_model_specific": float(getattr(result, "rsquared", float("nan"))),
                            "standard_errors": result.std_errors.to_dict(), "p_values": result.pvalues.to_dict(),
                            "estimated_effects": json.loads(estimated_effects.reset_index().to_json(orient="records", date_format="iso")) if estimated_effects is not None else None,
                            "period_parameters": json.loads(period_parameters.reset_index().to_json(orient="records", date_format="iso")) if period_parameters is not None else None,
                            "covariance_type": parameters.get("cov_type", "unadjusted"),
                            "entity_effects": bool(getattr(model, "entity_effects", False)) if model_id == "fixed_effects" else False,
                            "time_effects": bool(getattr(model, "time_effects", False)) if model_id == "fixed_effects" else False,
                            "forecast_available": not (model_id == "first_difference" or (model_id == "fixed_effects" and time_effects)),
                            "evaluation_unavailable_reason": "differenced_equation_has_no_level_prediction_contract" if model_id == "first_difference" else "future_time_effect_unobserved" if model_id == "fixed_effects" and time_effects else None,
                            "prediction_includes_entity_effects": bool(model_id == "fixed_effects" and entity_effects and not time_effects)}
    raise ModelingError("unsupported_model_adapter", model_id)


def validate_model_request(model_id: str, dataset: Mapping[str, Any], *, parameters: Mapping[str, Any] | None = None) -> dict[str, Any]:
    try:
        return _validate_model_request_impl(model_id, dataset, parameters=parameters)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ModelingError("invalid_model_parameter", f"{model_id} parameter value is invalid: {exc}", 422) from exc


def _validate_model_request_impl(model_id: str, dataset: Mapping[str, Any], *, parameters: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Preflight the same effective capability used by Preview and execution."""
    parameters = dict(parameters or {})
    inventory = _capability_for(model_id, classification=bool(dataset.get("label_definition") or dataset.get("class_counts")), parameters=parameters)
    if inventory is None: raise ModelingError("unknown_model", model_id)
    if not inventory["available"]:
        unsupported = inventory["unavailable_kind"] == "unsupported"
        raise ModelingError("capability_unavailable" if unsupported else "dependency_unavailable",
                            inventory["unavailable_reason"], 422 if unsupported else 503)
    unknown = set(parameters) - set(inventory["runtime_parameters"])
    if unknown:
        raise ModelingError("unsupported_model_parameter", f"{model_id} does not support parameters: {', '.join(sorted(unknown))}", 422)
    missing = [name for name in inventory["required_parameters"] if name not in parameters or parameters[name] is None]
    if missing:
        code = {"wls": "missing_wls_weight_contract", "gls": "missing_gls_covariance_basis",
                "vecm": "missing_cointegration_rank_basis", "sarima": "missing_seasonal_specification",
                "sarimax": "future_exog_unproven" if "future_exog_contract" in missing else "missing_seasonal_specification",
                "holt_winters": "missing_seasonal_frequency"}.get(model_id, "missing_model_parameter")
        raise ModelingError(code, f"{model_id} requires: {', '.join(missing)}", 422)
    if dataset.get("shape") != inventory["input_shape"]:
        raise ModelingError("invalid_model_input_shape", f"{model_id} requires {inventory['input_shape']}", 422)
    if dataset["shape"] == "supervised" and len(dataset.get("y_columns", [])) != 1:
        raise ModelingError("invalid_target_count", "supervised Stage 1 models require one Y target", 422)
    if dataset["shape"] in {"univariate_time_series", "multivariate_time_series"} and dataset.get("x_columns"):
        raise ModelingError("unsupported_model_inputs", f"{model_id} does not consume separate X inputs", 422)
    if dataset["shape"] == "multivariate_time_series" and len(dataset.get("y_columns", [])) < 2:
        raise ModelingError("insufficient_multivariate_series", f"{model_id} requires at least two Y series", 422)
    if dataset["shape"] == "panel" and (not dataset.get("entity_ids") or len(dataset.get("y_columns", [])) != 1):
        raise ModelingError("invalid_panel_input", "panel models require accepted entities and one Y target", 422)
    if "X" in inventory["required_inputs"] and not dataset.get("x_columns"):
        raise ModelingError("missing_model_regressors", f"{model_id} requires X", 422)
    classification = bool(dataset.get("label_definition") or dataset.get("class_counts"))
    if classification and inventory["family"] != "classification":
        raise ModelingError("invalid_model_task", f"{model_id} does not consume a classification target", 422)
    if not classification and inventory["family"] == "classification":
        raise ModelingError("classification_target_required", f"{model_id} requires a declared class target", 422)
    if classification:
        train_end = int(dataset["partitions"]["train"][1])
        target_index = list(dataset["columns"]).index(dataset["y_columns"][0])
        training_classes = set(np.asarray(dataset["values"], dtype=float)[:train_end, target_index].tolist())
        if len(training_classes) < 2:
            raise ModelingError("insufficient_training_classes", "classification requires at least two training classes", 422)
        if model_id == "logistic_regression" and training_classes != {0.0, 1.0}:
            raise ModelingError("invalid_classification_target", "Logistic Regression requires binary classes 0 and 1", 422)
    if model_id == "wls" and ("weights" not in parameters or not parameters.get("weights_basis")):
        raise ModelingError("missing_wls_weight_contract", "WLS requires explicit weights and their basis", 422)
    if model_id == "gls" and not parameters.get("sigma_basis"):
        raise ModelingError("missing_gls_covariance_basis", "GLS covariance requires an explicit basis", 422)
    train_rows = int(dataset["partitions"]["train"][1])
    if model_id == "wls":
        weights = np.asarray(parameters["weights"], dtype=float)
        if weights.shape != (train_rows,) or not np.all(np.isfinite(weights)) or np.any(weights <= 0):
            raise ModelingError("invalid_model_weights", "WLS weights must be finite, positive and match training rows", 422)
    if model_id == "gls":
        sigma = np.asarray(parameters["sigma"], dtype=float)
        if sigma.shape != (train_rows, train_rows) or not np.all(np.isfinite(sigma)) or not np.allclose(sigma, sigma.T) or np.min(np.linalg.eigvalsh(sigma)) <= 0:
            raise ModelingError("invalid_gls_covariance", "GLS sigma must be finite, symmetric, positive definite and match training rows", 422)
    for key in ("alpha", "tol"):
        if key in parameters and float(parameters[key]) <= 0:
            raise ModelingError("invalid_model_parameter", f"{key} must be positive", 422)
    if "l1_ratio" in parameters and not 0 <= float(parameters["l1_ratio"]) <= 1:
        raise ModelingError("invalid_model_parameter", "l1_ratio must be within [0, 1]", 422)
    for key in ("max_iter", "maxiter", "max_depth", "min_samples_leaf", "n_estimators", "simulations", "lags"):
        if key in parameters and int(parameters[key]) < 1:
            raise ModelingError("invalid_model_parameter", f"{key} must be positive", 422)
    if "order" in parameters and model_id in {"ar", "ma", "arma", "arima", "sarima", "sarimax"}:
        order = tuple(parameters["order"])
        if len(order) != 3 or any(not isinstance(value, int) or value < 0 for value in order):
            raise ModelingError("invalid_arima_order", "ARIMA order must contain three nonnegative integers", 422)
    if model_id in {"var", "vecm"} and "forecast_steps" in parameters and int(parameters["forecast_steps"]) < 1:
        raise ModelingError("invalid_forecast_steps", "forecast horizon must be positive", 422)
    if model_id == "vecm":
        rank = int(parameters.get("coint_rank", 1))
        if rank < 1 or rank >= len(dataset["y_columns"]) or int(parameters.get("k_ar_diff", 1)) < 0:
            raise ModelingError("invalid_vecm_rank", "VECM rank must be below vector width and lag difference nonnegative", 422)
    if model_id in {"markov_regression", "markov_autoregression"} and int(parameters.get("k_regimes", 2)) < 2:
        raise ModelingError("invalid_regime_count", "Markov models require at least two regimes", 422)
    if model_id in {"arch", "garch", "egarch", "gjr_tarch", "aparch"}:
        target_ops = [op.get("name") for op in dataset.get("spec", {}).get("y", [{}])[0].get("transformations", [])]
        if not target_ops or target_ops[-1] not in {"percentage_return", "log_return"}:
            raise ModelingError("invalid_volatility_target", "volatility model requires an explicit return or log-return model-space target", 422)
        p_order = int(parameters.get("p", 1))
        o_order = int(parameters.get("o", 1 if model_id == "gjr_tarch" else 0))
        q_order = int(parameters.get("q", 1))
        if p_order < 1 or o_order < 0 or (model_id != "arch" and q_order < 1):
            raise ModelingError("invalid_volatility_order", "volatility lag orders are outside the supported process contract", 422)
        if model_id == "aparch" and o_order > p_order:
            raise ModelingError("invalid_aparch_order", "APARCH asymmetric order cannot exceed p", 422)
        if model_id == "arch" and "q" in parameters:
            raise ModelingError("unsupported_model_parameter", "ARCH has no GARCH q term", 422)
    if model_id in {"sarima", "sarimax"}:
        seasonal = tuple(parameters.get("seasonal_order", ()))
        if len(seasonal) != 4 or seasonal[3] <= 1 or not any(seasonal[:3]) or not dataset.get("spec", {}).get("frequency"):
            raise ModelingError("missing_seasonal_specification", "SARIMA requires a nonzero seasonal order, period and declared observation frequency", 422)
        if int(dataset["partitions"]["train"][1]) < 2 * int(seasonal[3]):
            raise ModelingError("insufficient_seasonal_cycles", "seasonal estimation requires at least two training cycles", 422)
    if model_id == "holt_winters":
        if not dataset.get("spec", {}).get("frequency") or int(parameters.get("seasonal_periods", 0)) < 2:
            raise ModelingError("missing_seasonal_frequency", "Holt-Winters requires declared input frequency and seasonal period", 422)
        if int(dataset["partitions"]["train"][1]) < 2 * int(parameters["seasonal_periods"]):
            raise ModelingError("insufficient_seasonal_cycles", "Holt-Winters requires at least two training cycles", 422)
    if model_id == "vecm" and not parameters.get("rank_basis"):
        raise ModelingError("missing_cointegration_rank_basis", "VECM rank must have an explicit research basis", 422)
    if model_id in {"ar", "ma", "arma"} and "order" in parameters:
        order = tuple(parameters["order"])
        valid = (len(order) == 3 and all(isinstance(value, int) and value >= 0 for value in order) and
                 order[1] == 0 and ((model_id == "ar" and order[0] > 0 and order[2] == 0) or
                                    (model_id == "ma" and order[0] == 0 and order[2] > 0) or
                                    (model_id == "arma" and order[0] > 0 and order[2] > 0)))
        if not valid:
            raise ModelingError("incompatible_arima_family_order", f"{model_id} order contradicts its declared model family", 422)
    if model_id == "sarimax" and dataset.get("x_columns"):
        contract = parameters.get("future_exog_contract") or {}
        if contract.get("kind") != "scenario" or not contract.get("values") or not contract.get("basis"):
            raise ModelingError("future_exog_unproven", "SARIMAX future X requires explicit scenario values and basis", 422)
        test = dataset["partitions"]["test"]
        future_x = np.asarray(contract["values"], dtype=float)
        scenario_steps = int(parameters.get("forecast_steps", int(test[1]) - int(test[0])))
        if future_x.shape != (scenario_steps, len(dataset["x_columns"])) or not np.all(np.isfinite(future_x)):
            raise ModelingError("invalid_future_exog", "scenario X must match the chosen forecast horizon and regressors", 422)
    if model_id == "sarimax" and not dataset.get("x_columns"):
        raise ModelingError("sarimax_exogenous_required", "this SARIMAX contract requires an explicit X; use SARIMA otherwise", 422)
    if "forecast_steps" in parameters:
        steps = int(parameters["forecast_steps"])
        test = dataset.get("partitions", {}).get("test", [0, 0])
        if steps < 1 or steps > int(test[1]) - int(test[0]):
            raise ModelingError("invalid_forecast_steps", "evaluated forecast steps must fit inside the held-out interval", 422)
    if model_id == "aparch" and "delta" in parameters:
        delta = float(parameters["delta"])
        if not 0.05 < delta < 4.0:
            raise ModelingError("invalid_aparch_delta", "fixed APARCH delta must be in (0.05, 4.0)", 422)
    if model_id == "gjr_tarch" and "power" in parameters and float(parameters["power"]) not in {1.0, 2.0}:
        raise ModelingError("invalid_volatility_power", "GJR/TARCH power must be 1 or 2", 422)
    return inventory


def fit_model(model_id: str, dataset: Mapping[str, Any], *, parameters: Mapping[str, Any] | None = None) -> dict[str, Any]:
    parameters = dict(parameters or {})
    inventory = validate_model_request(model_id, dataset, parameters=parameters)
    x_train, y_train, x_test, y_test = _split_xy(dataset)
    train_end = int(dataset["partitions"]["train"][1])
    training_sample_digest = digest({"input_digest": dataset.get("input_digest"),
                                     "dates": list(dataset["dates"][:train_end]),
                                     "entity_ids": list(dataset.get("entity_ids", []))[:train_end]})
    if "forecast_steps" in parameters and (int(parameters["forecast_steps"]) < 1 or int(parameters["forecast_steps"]) > len(y_test)):
        raise ModelingError("invalid_forecast_steps", "evaluated forecast steps must fit inside the held-out interval", 422)
    if dataset["shape"] == "univariate_time_series":
        values = np.asarray(dataset["values"], dtype=float); boundary = dataset["partitions"]["train"][1]
        y_train = values[:boundary, 0]; y_test = values[boundary:, 0]; x_train = np.arange(len(y_train), dtype=float).reshape(-1, 1); x_test = np.arange(len(y_train), len(y_train) + len(y_test), dtype=float).reshape(-1, 1)
    classification = bool(dataset.get("label_definition") or dataset.get("class_counts"))
    if classification and len(set(np.asarray(y_train).reshape(-1).tolist())) < 2:
        raise ModelingError("insufficient_training_classes", "classification requires at least two classes in the training fold", 422)
    if model_id == "logistic_regression" and not classification:
        raise ModelingError("classification_target_required", "Logistic Regression requires a declared classification target", 422)
    if classification and not ({"class_label", "positive_class_probability"} & set(inventory["output_kinds"])):
        raise ModelingError("invalid_model_task", f"{model_id} cannot fit a classification target", 422)
    details: dict[str, Any]
    if model_id in {"ols", "ridge"}:
        coef, _ = _ols(x_train, y_train[:, 0], float(parameters.get("alpha", 1.0) if model_id == "ridge" else 0.0)); predictions = np.column_stack([np.ones(len(x_test)), x_test]) @ coef; details = {"coefficients": coef.tolist(), "intercept_included": True}
    elif model_id == "logistic_regression":
        labels = np.asarray(y_train[:, 0], dtype=float); unique = sorted(set(labels.tolist()))
        if unique != [0.0, 1.0]: raise ModelingError("invalid_classification_target", "Logistic Regression requires both binary classes 0 and 1 in training")
        from sklearn.linear_model import LogisticRegression
        estimator = LogisticRegression(max_iter=int(parameters.get("max_iter", 1000)), tol=float(parameters.get("tol", 1e-4)), random_state=int(parameters.get("seed", 0)))
        estimator.fit(x_train, labels.astype(int))
        if int(estimator.n_iter_[0]) >= estimator.max_iter:
            raise ModelingError("logistic_nonconvergence", "Logistic Regression reached max_iter without convergence", 422)
        predictions = estimator.predict_proba(x_test)[:, 1]
        details = {"coefficients": estimator.coef_[0].tolist(), "intercept": estimator.intercept_.tolist(),
                   "classes": estimator.classes_.tolist(), "prediction_kind": "positive_class_probability",
                   "class_threshold": 0.5, "solver": estimator.solver, "penalty": "l2", "iterations": estimator.n_iter_.tolist()}
    elif inventory["adapter"] in {"statsmodels", "linearmodels", "arch"}:
        train_target = y_train[:, 0] if np.asarray(y_train).ndim == 2 else np.asarray(y_train)
        test_target = y_test[:, 0] if np.asarray(y_test).ndim == 2 else np.asarray(y_test)
        try:
            predictions, details = _fit_optional_model(model_id, dataset, parameters, x_train, train_target, x_test, test_target)
        except ModelingError:
            raise
        except Exception as exc:
            raise ModelingError("model_fit_failed", f"{model_id} fitting failed: {exc}", 422, {"model_id": model_id}) from exc
        if model_id in {"wls", "gls"}:
            details["training_sample_digest"] = training_sample_digest
    else:
        if inventory["adapter"] != "sklearn":
            raise ModelingError("unsupported_model_adapter", f"{model_id} has no declared adapter", 500)
        if not importlib.util.find_spec("sklearn"): raise ModelingError("dependency_unavailable", "scikit-learn is required for this model", 503)
        from sklearn.ensemble import ExtraTreesClassifier, ExtraTreesRegressor, GradientBoostingClassifier, GradientBoostingRegressor, RandomForestClassifier, RandomForestRegressor
        from sklearn.linear_model import ElasticNet, Lasso
        from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor
        regression = {"random_forest": RandomForestRegressor, "extra_trees": ExtraTreesRegressor, "gradient_boosting": GradientBoostingRegressor, "decision_tree": DecisionTreeRegressor, "lasso": Lasso, "elastic_net": ElasticNet}
        classification_classes = {"random_forest": RandomForestClassifier, "extra_trees": ExtraTreesClassifier, "gradient_boosting": GradientBoostingClassifier, "decision_tree": DecisionTreeClassifier}
        if classification and model_id in classification_classes:
            config = {key: parameters[key] for key in ("max_depth", "min_samples_leaf", "n_estimators") if key in parameters}
            estimator = classification_classes[model_id](random_state=int(parameters.get("seed", 0)), **config)
            estimator.fit(x_train, y_train[:, 0].astype(int))
            predictions = estimator.predict(x_test)
            details = {"classes": estimator.classes_.tolist(), "feature_importance": getattr(estimator, "feature_importances_", np.array([])).tolist(),
                       "class_probabilities": estimator.predict_proba(x_test).tolist(), "estimator_parameters": config,
                       "prediction_kind": "class_label"}
        else:
            if classification:
                raise ModelingError("invalid_model_task", f"{model_id} has no classification adapter", 422)
            config = {key: parameters[key] for key in ("alpha", "l1_ratio", "max_iter", "tol", "max_depth", "min_samples_leaf", "n_estimators") if key in parameters}
            if model_id in {"lasso", "elastic_net"}:
                estimator = regression[model_id](**config)
            else:
                estimator = regression[model_id](random_state=int(parameters.get("seed", 0)), **config)
            estimator.fit(x_train, y_train[:, 0]); predictions = estimator.predict(x_test)
            if hasattr(estimator, "n_iter_") and int(estimator.n_iter_) >= int(estimator.max_iter):
                raise ModelingError("regularized_fit_nonconvergence", f"{model_id} reached max_iter without convergence", 422)
            details = {"feature_importance": getattr(estimator, "feature_importances_", np.array([])).tolist(),
                       "estimator_parameters": config, "iterations": int(estimator.n_iter_) if hasattr(estimator, "n_iter_") else None}
    predicted = np.asarray(predictions)
    test_start = int(dataset["partitions"]["test"][0])
    predicted_count = int(predicted.shape[0]) if predicted.ndim else 0
    actual_matrix = np.asarray(y_test, dtype=float).reshape(len(y_test), -1)[:predicted_count]
    test_origin_dates = list(dataset["dates"][test_start:test_start + predicted_count])
    all_target_dates = list(dataset.get("target_dates", dataset["dates"]))
    test_target_dates = all_target_dates[test_start:test_start + predicted_count]
    if dataset["shape"] in {"univariate_time_series", "multivariate_time_series"}:
        forecast_origin = dataset["dates"][test_start - 1]
        test_origin_dates = [forecast_origin] * predicted_count
    output_kind = ("conditional_volatility" if details.get("forecast_kind") == "conditional_volatility" else
                   "conditional_scenario_mean" if details.get("forecast_kind") == "conditional_scenario_mean" else
                   "vector_forecast" if dataset["shape"] == "multivariate_time_series" else
                   "state_probabilities" if inventory["family"] == "regime_state" and not details.get("forecast_available", True) else
                   "positive_class_probability" if model_id == "logistic_regression" else
                   "class_label" if classification else
                   "fit_only_diagnostic" if details.get("forecast_available") is False else
                   "conditional_mean" if inventory["supports_forecast"] else "numeric_prediction")
    if output_kind == "positive_class_probability":
        value_type, output_unit, meaning = "probability", "dimensionless", "positive-class probability"
    elif output_kind == "class_label":
        value_type, output_unit, meaning = "class_label", "dimensionless", "declared target label"
    elif output_kind == "state_probabilities":
        value_type, output_unit, meaning = "probability_vector", "dimensionless", "in-sample filtered regime probabilities; smoothed probabilities remain model diagnostics"
    elif output_kind == "conditional_volatility":
        value_type, output_unit, meaning = "volatility", details["input_return_unit"], "conditional target-change volatility"
    elif output_kind == "conditional_scenario_mean":
        value_type, output_unit, meaning = "scenario_numeric", "model_space_target_unit", "conditional mean under supplied future-X scenario"
    elif details.get("forecast_available") is False:
        value_type, output_unit, meaning = "fit_only_diagnostic", "model_space_target_unit", "fit-only diagnostic; no held-out level forecast"
    elif output_kind == "vector_forecast":
        value_type, output_unit, meaning = "numeric_vector", "model_space_target_unit", "one value per endogenous target"
    else:
        value_type, output_unit, meaning = "numeric", "model_space_target_unit", "model-space numeric estimate/forecast"
    target_contract = {name: dict(dataset.get("target_contract", {}).get(name, {})) for name in dataset["y_columns"]}
    model_units = {name: target_contract.get(name, {}).get("model_space_unit") for name in dataset["y_columns"]}
    contract_units = {name: output_unit if output_unit != "model_space_target_unit" else model_units.get(name)
                      for name in dataset["y_columns"]}
    output_contract = {"kind": output_kind, "value_type": value_type, "unit": output_unit,
                       "meaning": meaning, "target_columns": list(dataset["y_columns"]),
                       "target_contract": target_contract, "unit_by_target": contract_units}
    metrics: dict[str, Any] = {"evaluation_row_count": predicted_count}
    if predicted_count and details.get("forecast_kind") not in {"conditional_volatility", "conditional_scenario_mean"}:
        metrics["test_count"] = predicted_count
    if details.get("forecast_kind") == "conditional_volatility":
        # Volatility models forecast conditional variance/volatility, not the
        # raw level of Y.  Do not report level RMSE/R2 against that quantity.
        metrics.update({"forecast_kind": "conditional_volatility",
                        "conditional_variance_count": len(details.get("conditional_variance", [])),
                        "conditional_volatility_count": len(details.get("conditional_volatility", []))})
    elif details.get("forecast_kind") == "conditional_scenario_mean":
        metrics.update({"evaluation_available": False, "reason": "conditional_future_exogenous_scenario_is_not_observed_history"})
    elif details.get("forecast_available") is False:
        metrics.update({"forecast_available": False, "fit_only": True})
        if inventory["family"] == "regime_state":
            metrics["state_only_fit"] = True
    elif predicted_count:
        if classification:
            predicted_class = (predicted.reshape(-1) >= 0.5).astype(int) if model_id == "logistic_regression" else predicted.reshape(-1).astype(int)
            actual_class = actual_matrix[:, 0].astype(int)
            tp = int(np.sum((predicted_class == 1) & (actual_class == 1)))
            fp = int(np.sum((predicted_class == 1) & (actual_class != 1)))
            fn = int(np.sum((predicted_class != 1) & (actual_class == 1)))
            metrics["accuracy"] = float(np.mean(predicted_class == actual_class))
            if set(actual_class.tolist()) | set(predicted_class.tolist()) <= {0, 1}:
                metrics.update({"precision": float(tp / (tp + fp)) if tp + fp else None,
                                "recall": float(tp / (tp + fn)) if tp + fn else None,
                                "positive_count": int(np.sum(predicted_class == 1))})
            else:
                metrics["per_class"] = {}
                for label in sorted(set(actual_class.tolist()) | set(predicted_class.tolist())):
                    true_positive = int(np.sum((predicted_class == label) & (actual_class == label)))
                    predicted_positive = int(np.sum(predicted_class == label))
                    actual_positive = int(np.sum(actual_class == label))
                    metrics["per_class"][str(label)] = {"precision": true_positive / predicted_positive if predicted_positive else None,
                                                        "recall": true_positive / actual_positive if actual_positive else None}
        elif dataset["shape"] == "multivariate_time_series":
            if predicted.shape != actual_matrix.shape:
                raise ModelingError("invalid_vector_forecast_shape", "forecast must contain every endogenous target", 422)
            metrics["per_target"] = {}
            for column, name in enumerate(dataset["y_columns"]):
                residual = predicted[:, column] - actual_matrix[:, column]
                metrics["per_target"][name] = {"rmse": float(np.sqrt(np.mean(residual ** 2))),
                                                "mae": float(np.mean(np.abs(residual)))}
        else:
            actual = actual_matrix[:, 0]; pred = predicted.reshape(-1)
            if len(pred) != len(actual):
                raise ModelingError("prediction_length_mismatch", "prediction rows do not match actual evaluation rows", 422)
            residual = pred - actual
            metrics.update({"rmse": float(np.sqrt(np.mean(residual ** 2))), "mae": float(np.mean(np.abs(residual))),
                            "r2": float(1 - np.sum(residual ** 2) / np.sum((actual - np.mean(actual)) ** 2)) if np.var(actual) else None})
    output_values = predicted.tolist()
    if output_kind == "state_probabilities":
        output_values = details["filtered_state_probabilities"]
        test_origin_dates = list(details["state_dates"])
        test_target_dates = list(details["state_dates"])
    test_entity_ids = list(dataset.get("entity_ids", []))[test_start:test_start + predicted_count]
    test_listing_ids = list(dataset.get("listing_ids", []))[test_start:test_start + predicted_count]
    sample_identity = digest({"input_digest": dataset.get("input_digest"), "origin_dates": test_origin_dates,
                              "target_dates": test_target_dates, "entity_ids": test_entity_ids,
                              "listing_ids": test_listing_ids,
                              "y_columns": dataset["y_columns"], "actual": actual_matrix.tolist()})
    y_unit_contract: dict[str, Any] = {}
    for variable in dataset.get("spec", {}).get("y", []):
        operations = [str(op.get("name", "raw")) for op in variable.get("transformations", [])]
        if "standardize" in operations:
            y_unit_contract[variable["name"]] = "training_standard_score"
        elif "percentage_return" in operations:
            y_unit_contract[variable["name"]] = "decimal_percentage_change"
        elif "log_return" in operations:
            y_unit_contract[variable["name"]] = "log_change"
        elif "first_difference" in operations:
            y_unit_contract[variable["name"]] = {"kind": "first_difference", "source": dataset.get("source_representation", {}).get(variable["series_key"])}
        else:
            y_unit_contract[variable["name"]] = dataset.get("source_representation", {}).get(variable["series_key"], [[None, None, None]])
    output = {"kind": output_kind, "value_type": value_type, "values": output_values, "target_columns": list(dataset["y_columns"]),
              "origin_dates": test_origin_dates, "target_dates": test_target_dates,
              "output_unit": output_unit, "output_contract": output_contract,
              "target_contract": target_contract, "model_space_unit_by_target": y_unit_contract,
              "evaluation_sample_digest": sample_identity}
    if dataset["shape"] == "panel":
        # Keep the arrays as a small compatibility projection for the accepted
        # frontend contract; row_identity is the authoritative self-describing
        # representation used by API consumers and exports.
        output["entity_ids"] = test_entity_ids
        output["listing_ids"] = test_listing_ids
        output["row_identity"] = [
            {"entity_id": entity_id, "listing_id": listing_id}
            for entity_id, listing_id in zip(test_entity_ids, test_listing_ids)
        ]
        output["row_identity_contract"] = {
            "kind": "panel_prediction_row_identity",
            "fields": ["entity_id", "listing_id"],
            "identity_owner": "release_bound_accepted_equity_listing_identity",
            "alignment": "one entry per output row in origin_dates/target_dates/values order",
        }
    if output_kind not in inventory.get("output_kinds", []):
        raise ModelingError("capability_output_mismatch", f"{model_id} produced undeclared output kind {output_kind}", 500)
    family_result_kind = ("panel_first_difference" if model_id == "first_difference" else
                          "panel_repeated_period" if model_id == "fama_macbeth" else
                          "panel_fit_only" if inventory["family"] == "panel" and output_kind == "fit_only_diagnostic" else
                          "panel_level" if inventory["family"] == "panel" else
                          "markov_regime" if model_id in {"markov_regression", "markov_autoregression"} else
                          "structural_state" if model_id == "unobserved_components" else inventory["family"])
    _validate_family_result(inventory, output, metrics)
    distribution = {"sklearn": "scikit-learn", "statsmodels": "statsmodels", "linearmodels": "linearmodels",
                    "arch": "arch"}.get(inventory["adapter"])
    library_version = importlib_metadata.version(distribution) if distribution else "fr_native_v1"
    return {"schema_version": "fr_model_family_result_v1", "model_id": model_id, "family": inventory["family"],
            "adapter": inventory["adapter"], "library_version": library_version, "metrics": metrics,
            "family_result": {"kind": family_result_kind, "model_id": model_id, "data": details},
            "output": output, "test_dates": test_target_dates,
            "task_parameters": {key: parameters[key] for key in inventory["task_parameters"] if key in parameters},
            "model_configuration": {key: value for key, value in parameters.items() if key not in inventory["task_parameters"]},
            "evaluation_contract": {"sample_digest": sample_identity, "split": dataset["partitions"],
                                    "metric_names": sorted(set(metrics) & {"rmse", "mae", "r2", "accuracy", "precision", "recall", "per_target", "per_class"})},
            "input_digest": dataset.get("input_digest"),
            "task_semantics": "supervised_target_shift" if dataset.get("horizon") else "model_native_forecast" if inventory["supports_forecast"] else "contemporaneous_estimation"}


def _validate_family_result(contract: Mapping[str, Any], output: Mapping[str, Any], metrics: Mapping[str, Any]) -> None:
    """Validate new results against the same effective capability as Preview."""
    if output.get("kind") not in contract["output_kinds"]:
        raise ModelingError("capability_output_mismatch", "model output violates its effective family contract", 500)
    evaluative = {"rmse", "mae", "r2", "accuracy", "precision", "recall", "per_target", "per_class"}
    leaked = (set(metrics) & evaluative) - set(contract["metrics"])
    if leaked:
        raise ModelingError("capability_metric_mismatch", f"model emitted undeclared metrics: {', '.join(sorted(leaked))}", 500)
    if output["kind"] in {"class_label", "positive_class_probability", "state_probabilities"} and output.get("output_unit") != "dimensionless":
        raise ModelingError("capability_unit_mismatch", "class and state outputs must be dimensionless", 500)


def validate_comparison_request(model_ids: Sequence[str], dataset: Mapping[str, Any], *, parameters: Mapping[str, Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Reject incompatible research questions before any estimator fit or claim."""
    ids = list(dict.fromkeys(model_ids))
    if len(ids) < 2: raise ModelingError("comparison_requires_multiple_models", "choose at least two models")
    if dataset.get("shape") not in {"supervised", "univariate_time_series", "multivariate_time_series", "panel"}:
        raise ModelingError("incomparable_input_shape", "comparison requires an evaluated Modeling input")
    contracts = [validate_model_request(model_id, dataset, parameters=(parameters or {}).get(model_id)) for model_id in ids]
    groups = {item["comparison_group"] for item in contracts}
    if len(groups) != 1 or not next(iter(groups)):
        raise ModelingError("incomparable_model_contract", "models do not share a supported comparison family", 422)
    horizons = {int(((parameters or {}).get(model_id) or {}).get("forecast_steps", dataset["partitions"]["test"][1] - dataset["partitions"]["test"][0])) for model_id in ids}
    if len(horizons) != 1:
        raise ModelingError("incomparable_forecast_horizon", "comparison models must use the same forecast horizon", 422)
    if set((parameters or {})) - set(ids):
        raise ModelingError("unknown_comparison_parameters", "parameters name a model outside the comparison", 422)
    return contracts


def compare_models(model_ids: Sequence[str], dataset: Mapping[str, Any], *, parameters: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Compare compatible adapters over the same frozen dataset and split."""
    ids = list(dict.fromkeys(model_ids))
    validate_comparison_request(ids, dataset, parameters=parameters)
    results = [fit_model(model_id, dataset, parameters=(parameters or {}).get(model_id)) for model_id in ids]
    first = results[0]["output"]
    comparable_kind = lambda kind: "class_label_evaluation" if kind in {"positive_class_probability", "class_label"} else kind
    for result in results[1:]:
        current = result["output"]
        if (comparable_kind(current["kind"]), current["target_columns"], current["origin_dates"], current["target_dates"],
            current["evaluation_sample_digest"]) != (comparable_kind(first["kind"]), first["target_columns"], first["origin_dates"],
                                                   first["target_dates"], first["evaluation_sample_digest"]):
            raise ModelingError("incomparable_model_outputs", "models do not share target, timing, output meaning and evaluation sample", 422)
    classification = bool(dataset.get("label_definition") or dataset.get("class_counts"))
    declared = set.intersection(*(
        set((_capability_for(model_id, classification=classification, parameters=(parameters or {}).get(model_id)) or {}).get("metrics", [])) for model_id in ids))
    common = (set.intersection(*(set(result["metrics"]) for result in results)) & declared) - {
        "test_count", "evaluation_row_count", "positive_count"}
    if first["kind"] in {"conditional_volatility", "state_probabilities", "conditional_scenario_mean"} or not common:
        raise ModelingError("incomparable_model_metrics", "these model outputs have no shared validated evaluation metric", 422)
    if first["kind"] == "vector_forecast" and "per_target" in common:
        common = [f"per_target.{name}.{metric}" for name in first["target_columns"] for metric in ("rmse", "mae")
                  if all(isinstance(result["metrics"].get("per_target", {}).get(name, {}).get(metric), (int, float))
                         for result in results)]
    else:
        common = sorted(key for key in common if all(isinstance(result["metrics"].get(key), (int, float)) and result["metrics"][key] is not None for result in results))
    if not common:
        raise ModelingError("incomparable_model_metrics", "the shared metric must be numeric and defined for every model", 422)
    return {"schema_version": "fr_model_comparison_v1", "input_digest": dataset.get("input_digest"),
            "models": results, "comparison_metrics": common,
            "winner": None, "winner_policy": "researcher_decides"}


def validate_optimization_request(model_id: str, dataset: Mapping[str, Any], *, search_space: Mapping[str, Sequence[Any]], fixed_parameters: Mapping[str, Any] | None = None, seed: int = 0) -> dict[str, Any]:
    fixed = dict(fixed_parameters or {})
    inventory = _capability_for(model_id, classification=bool(dataset.get("label_definition") or dataset.get("class_counts")), parameters=fixed)
    if inventory is None or not inventory["available"] or not inventory["supports_tuning"]:
        raise ModelingError("optimization_unsupported", "this model has no supported train/validation scoring contract", 422)
    if seed != 0:
        raise ModelingError("optimization_seed_unsupported", "deterministic grid search does not consume a random seed", 422)
    if inventory["supports_forecast"] and "forecast_steps" not in fixed:
        raise ModelingError("forecast_horizon_required", "optimization must freeze forecast_steps as a task parameter", 422)
    if inventory["supports_forecast"]:
        train_end = int(dataset["partitions"]["train"][1])
        inner_end = _chronological_train_end(list(dataset["dates"][:train_end]), 0.8)
        try:
            fixed_horizon = int(fixed["forecast_steps"])
        except (ValueError, TypeError) as exc:
            raise ModelingError("invalid_forecast_steps", "forecast_steps must be an integer", 422) from exc
        if fixed_horizon > train_end - inner_end:
            raise ModelingError("inner_forecast_horizon_unavailable", "inner validation cannot evaluate the fixed forecast horizon", 422)
    if not search_space:
        raise ModelingError("optimization_search_space_required", "at least one tunable parameter is required", 422)
    illegal = set(search_space) - set(inventory["tunable_parameters"])
    if illegal:
        raise ModelingError("parameter_not_tunable", f"{model_id} cannot tune: {', '.join(sorted(illegal))}", 422)
    if set(search_space) & set(fixed):
        raise ModelingError("fixed_parameter_in_search", "a parameter cannot be both fixed and tuned", 422)
    if any(not list(values) for values in search_space.values()):
        raise ModelingError("empty_optimization_candidates", "each search parameter needs a candidate value", 422)
    candidate = {**fixed, **{key: list(values)[0] for key, values in search_space.items()}}
    validate_model_request(model_id, dataset, parameters=candidate)
    return inventory


def auto_optimize(model_id: str, dataset: Mapping[str, Any], *, search_space: Mapping[str, Sequence[Any]], budget: int = 20, seed: int = 0, fixed_parameters: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Small deterministic grid optimizer using train/validation only.

    The frozen dataset's test partition is held out.  Candidate datasets end at
    the original train boundary and split that prefix again for validation.
    """
    fixed = dict(fixed_parameters or {})
    inventory = validate_optimization_request(model_id, dataset, search_space=search_space, fixed_parameters=fixed, seed=seed)
    if budget < 1 or budget > 100: raise ModelingError("invalid_optimization_budget", "budget must be between 1 and 100")
    keys = list(search_space); candidates: list[dict[str, Any]] = [fixed]
    for key in keys:
        expanded = []
        for base in candidates:
            for value in list(search_space[key])[:budget]: expanded.append({**base, key: value})
        candidates = expanded[:budget]
    train_end = int(dataset["partitions"]["train"][1])
    if train_end < 4: raise ModelingError("insufficient_optimization_rows", "at least four outer-training rows are required")
    outer_dates = list(dataset["dates"][:train_end])
    validation_end = _chronological_train_end(outer_dates, 0.8)
    first_validation_date = outer_dates[validation_end]
    target_dates = list(dataset.get("target_dates", dataset["dates"]))[:train_end]
    purged = [i for i in range(validation_end) if target_dates[i] >= first_validation_date]
    retained = [i for i in range(train_end) if i not in set(purged)]
    inner_end = validation_end - len(purged)
    if inner_end < 2 or inner_end == len(retained):
        raise ModelingError("insufficient_inner_training_rows", "target-aware validation gap leaves insufficient rows")
    raw = np.asarray(dataset.get("raw_values", dataset["values"]), dtype=float)[retained]
    prepared, labels, counts, learned = _fit_fold_preprocessing(raw, dataset["spec"], dataset["columns"], inner_end)
    train_dataset = dict(dataset)
    train_dataset.update({"values": prepared.tolist(), "raw_values": raw.tolist(),
                          "dates": [dataset["dates"][i] for i in retained],
                          "target_dates": [target_dates[i] for i in retained],
                          "row_count": len(retained), "label_definition": labels,
                          "class_counts": counts, "learned_preprocessing": learned,
                          "partitions": {"train": [0, inner_end], "test": [inner_end, len(retained)], "kind": "chronological_validation"},
                          "purged_inner_train_rows": len(purged)})
    if "entity_ids" in dataset:
        train_dataset["entity_ids"] = [dataset["entity_ids"][i] for i in retained]
    train_dataset.pop("input_digest", None)
    train_dataset["input_digest"] = digest(train_dataset)
    scores = []
    metric = "accuracy" if inventory["family"] == "classification" else "rmse"
    for params in candidates:
        fitted = fit_model(model_id, train_dataset, parameters=params); score = fitted["metrics"].get(metric)
        if score is not None: scores.append({"parameters": params, "validation_metric": metric, "validation_score": score})
    if not scores: raise ModelingError("optimization_no_valid_candidate", "no candidate completed validation")
    best = (max if metric == "accuracy" else min)(scores, key=lambda row: row["validation_score"])
    final = fit_model(model_id, dataset, parameters=best["parameters"])
    return {"model_id": model_id, "search_contract": {"search_space": {k: list(v) for k, v in search_space.items()}, "fixed_parameters": fixed, "budget": budget, "seed": seed, "validation": "chronological_inner_train_with_target_gap", "inner_input_digest": train_dataset["input_digest"], "outer_input_digest": dataset["input_digest"], "purged_inner_train_rows": len(purged), "inner_preprocessing": learned}, "trials": scores, "selected": best, "final": final}


class ModelingRunStore:
    def __init__(self, root: Path | None = None):
        # Reads must not create runtime state.  A GET /models or a failed
        # readiness probe is not a Modeling execution.
        self.root = Path(root or (RUNTIME_ROOT / "modeling"))
        self.runs = self.root / "runs"
        self.candidates = self.root / "candidates"
        self.lock = self.root / "active.lock"
        self._mutex = threading.RLock()
        self._workers: dict[str, Any] = {}

    def _ensure_dirs(self) -> None:
        self.runs.mkdir(parents=True, exist_ok=True)

    def save_candidate(self, candidate: Mapping[str, Any]) -> str:
        self.candidates.mkdir(parents=True, exist_ok=True)
        candidate_id = uuid.uuid4().hex
        self._write_json_atomic(self.candidates / f"{candidate_id}.json", {"created_epoch": time.time(), "candidate": dict(candidate)})
        return candidate_id

    def _validate_candidate_id(self, candidate_id: str) -> None:
        if len(candidate_id) != 32 or any(c not in "0123456789abcdef" for c in candidate_id):
            raise ModelingError("invalid_candidate_id", "Preview candidate id is invalid")

    def _read_candidate(self, candidate_id: str, expected_digest: str) -> dict[str, Any]:
        self._validate_candidate_id(candidate_id)
        path = self.candidates / f"{candidate_id}.json"
        frozen = self._read_json(path)
        if not frozen or time.time() - float(frozen.get("created_epoch", 0)) > 3600:
            raise ModelingError("candidate_unavailable", "Preview candidate expired; refresh Preview", 409)
        candidate = dict(frozen["candidate"])
        if digest(candidate) != expected_digest:
            raise ModelingError("candidate_binding_mismatch", "Preview candidate changed; refresh Preview", 409)
        return candidate

    def peek_candidate(self, candidate_id: str, expected_digest: str) -> dict[str, Any]:
        """Read a candidate without claiming it for execution."""
        return self._read_candidate(candidate_id, expected_digest)

    def _claim_candidate_unlocked(self, candidate_id: str, expected_digest: str, run_id: str) -> dict[str, Any]:
        path = self.candidates / f"{candidate_id}.json"
        frozen = self._read_json(path)
        candidate = self._read_candidate(candidate_id, expected_digest)
        if frozen and frozen.get("claimed_run_id"):
            raise ModelingError("candidate_already_claimed", "this Preview candidate has already been used for a Run", 409,
                                 {"run_id": frozen.get("claimed_run_id")})
        self._write_json_atomic(path, {**frozen, "claimed_at_utc": _now(), "claimed_run_id": run_id})
        return candidate

    def create_from_candidate(self, candidate_id: str, expected_digest: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """Atomically claim one Preview candidate and reserve the execution slot."""
        with self._mutex:
            self._ensure_dirs()
            self.mark_orphaned()
            active = self.active()
            if active and active.get("status") in {"queued", "running", "recovering"}:
                raise ModelingError("modeling_busy", "one Modeling task is already running", 409, {"run_id": active.get("run_id")})
            run_id = f"modeling:{uuid.uuid4().hex}"
            owned_lock = False
            try:
                fd = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                owned_lock = True
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump({"run_id": run_id, "status": "queued", "owner_pid": os.getpid()}, handle)
                candidate = self._claim_candidate_unlocked(candidate_id, expected_digest, run_id)
                row = {"schema_version": SCHEMA_VERSION, "run_id": run_id, "status": "queued",
                       "created_at_utc": _now(), "updated_at_utc": _now(), "owner_pid": os.getpid(),
                       "candidate_id": candidate_id, "candidate_digest": expected_digest, **candidate}
                self._write_json_atomic(self._path(run_id), row)
                return row, candidate
            except FileExistsError as exc:
                raise ModelingError("modeling_busy", "one Modeling task is already running", 409) from exc
            except Exception:
                if owned_lock and (self.active() or {}).get("run_id") == run_id:
                    self.lock.unlink(missing_ok=True)
                raise

    def start_process(self, run_id: str, operation: str, dataset: Mapping[str, Any], model_or_ids: Any,
                      parameters_or_search: Mapping[str, Any] | Sequence[str], budget: int | None = None,
                      seed: int | None = None) -> dict[str, Any]:
        """Run a product Modeling task in a killable child process.

        The process owns fitting; the parent owns the durable run record and
        can terminate that owner on cancellation, releasing the installation
        slot without waiting for a long adapter call to return.
        """
        # Embedded test runners and interactive shells do not expose a
        # re-importable __main__ file, so Windows spawn cannot safely start a
        # child there.  The supported application launcher has a real file
        # entrypoint and uses the killable process path below.
        entrypoint = getattr(sys.modules.get("__main__"), "__file__", None)
        test_runner = entrypoint and any(token in str(entrypoint).casefold() for token in ("unittest", "pytest"))
        if not entrypoint or not Path(str(entrypoint)).is_file() or test_runner:
            if operation == "run":
                target, args = run_in_store, (self, run_id, dataset, str(model_or_ids), dict(parameters_or_search))
            elif operation == "comparison":
                target, args = run_comparison_in_store, (self, run_id, dataset, list(model_or_ids), dict(parameters_or_search))
            elif operation == "optimization":
                spec = dict(parameters_or_search)
                target, args = run_optimization_in_store, (self, run_id, dataset, str(model_or_ids), dict(spec.get("search_space", spec)), int(budget or 20), int(seed or 0), dict(spec.get("fixed_parameters", {})))
            else:
                raise ModelingError("invalid_modeling_operation", operation)
            threading.Thread(target=target, args=args, daemon=True).start()
            return {"run_id": run_id, "owner_pid": os.getpid(), "process_started": False, "thread_fallback": True}
        context = multiprocessing.get_context("spawn")
        self._workers = {key: worker for key, worker in self._workers.items() if worker.is_alive()}
        root = str(self.root)
        if operation == "run":
            target = run_in_store_process
            args = (root, run_id, dataset, str(model_or_ids), dict(parameters_or_search))
        elif operation == "comparison":
            target = run_comparison_in_store_process
            args = (root, run_id, dataset, list(model_or_ids), dict(parameters_or_search))
        elif operation == "optimization":
            target = run_optimization_in_store_process
            spec = dict(parameters_or_search)
            args = (root, run_id, dataset, str(model_or_ids), dict(spec.get("search_space", spec)), int(budget or 20), int(seed or 0), dict(spec.get("fixed_parameters", {})))
        else:
            raise ModelingError("invalid_modeling_operation", operation)
        process = context.Process(target=target, args=args, daemon=True)
        try:
            process.start()
        except Exception as exc:
            self.update(run_id, status="failed", error_code="modeling_process_start_failed", error_message=str(exc))
            raise ModelingError("modeling_process_start_failed", "Modeling compute process could not start", 503) from exc
        self._workers[run_id] = process
        return {"run_id": run_id, "owner_pid": process.pid, "process_started": True}

    def claim_candidate(self, candidate_id: str, expected_digest: str) -> dict[str, Any]:
        """Compatibility read for tooling; product execution uses create_from_candidate."""
        return self._read_candidate(candidate_id, expected_digest)

    @staticmethod
    def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        try:
            # On Windows a concurrent reader or virus scanner can briefly
            # hold the destination open without delete sharing.  The rename
            # remains atomic, but may need a bounded retry.
            for attempt in range(10):
                try:
                    os.replace(temporary, path)
                    break
                except PermissionError:
                    if attempt == 9:
                        raise
                    time.sleep(0.01 * (attempt + 1))
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        for attempt in range(5):
            try:
                if not path.is_file():
                    return None
                return json.loads(path.read_text(encoding="utf-8"))
            except (PermissionError, json.JSONDecodeError):
                if attempt == 4:
                    raise
                time.sleep(0.01 * (attempt + 1))
        return None

    def _path(self, run_id: str) -> Path:
        # The external run id keeps its readable namespace separator, while
        # the persisted filename is valid on Windows (':' is not).
        if not _RUN_ID.fullmatch(str(run_id)):
            raise ModelingError("invalid_run_id", "Modeling run id is invalid")
        safe_id = str(run_id).replace(":", "_")
        return self.runs / f"{safe_id}.json"
    def get(self, run_id: str) -> dict[str, Any] | None:
        return self._read_json(self._path(run_id))
    def list_recent(self, *, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        """Project bounded temporary run metadata from the existing run files."""
        if not 1 <= limit <= 50 or not 0 <= offset <= 1000:
            raise ModelingError("invalid_run_list_window", "Run list limit or offset is outside the supported range")
        if not self.runs.is_dir():
            return {"schema_version": "fr_modeling_run_list_v1", "runs": [], "limit": limit,
                    "offset": offset, "has_more": False}
        cutoff = time.time() - 24 * 3600
        paths = sorted(
            (path for path in self.runs.glob("modeling_*.json") if path.is_file() and not path.is_symlink()),
            key=lambda path: (path.stat().st_mtime, path.name), reverse=True,
        )
        selected: list[dict[str, Any]] = []
        eligible = 0
        for path in paths:
            row = self._read_json(path)
            if not row or not _RUN_ID.fullmatch(str(row.get("run_id") or "")):
                continue
            if path != self._path(row["run_id"]):
                continue
            status = str(row.get("status") or "")
            if status in {"completed", "cancelled", "failed", "interrupted"} and path.stat().st_mtime < cutoff:
                continue
            if eligible >= offset and len(selected) < limit + 1:
                execution = row.get("execution") or {}
                spec = row.get("spec") or {}
                binding = row.get("release_binding") or {}
                operation = row.get("operation") or execution.get("operation") or "run"
                model_id = row.get("model_id") or execution.get("model_id")
                result_available = status == "completed" and isinstance(row.get("result"), dict)
                selected.append({
                    "run_id": row["run_id"], "operation": operation,
                    "model_id": model_id, "model_ids": row.get("model_ids") or execution.get("model_ids") or [],
                    "status": status, "created_at_utc": row.get("created_at_utc"),
                    "updated_at_utc": row.get("updated_at_utc"), "completed_at_utc": row.get("completed_at_utc"),
                    "recoverable": status in {"interrupted", "failed"} and isinstance(row.get("dataset"), dict),
                    "result_available": result_available, "export_available": result_available,
                    "summary": {"shape": spec.get("shape"), "start": spec.get("start"), "end": spec.get("end"),
                                "target_names": [item.get("name") for item in spec.get("y", []) if isinstance(item, dict)],
                                "feature_count": len(spec.get("x", [])),
                                "release_id": binding.get("release_id")},
                })
            eligible += 1
            if len(selected) > limit:
                break
        return {"schema_version": "fr_modeling_run_list_v1", "runs": selected[:limit],
                "limit": limit, "offset": offset, "has_more": len(selected) > limit}
    def active(self) -> dict[str, Any] | None:
        if not self.lock.is_file(): return None
        try: return self._read_json(self.lock)
        except Exception: return None
    def create(self, candidate: Mapping[str, Any]) -> dict[str, Any]:
        with self._mutex:
            self._ensure_dirs()
            self.mark_orphaned()
            active = self.active()
            if active and active.get("status") in {"queued", "running", "recovering"}: raise ModelingError("modeling_busy", "one Modeling task is already running", 409, {"run_id": active.get("run_id")})
            run_id = f"modeling:{uuid.uuid4().hex}"; row = {"schema_version": SCHEMA_VERSION, "run_id": run_id, "status": "queued", "created_at_utc": _now(), "updated_at_utc": _now(), "owner_pid": os.getpid(), **dict(candidate)}
            try:
                fd = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as handle: json.dump({"run_id": run_id, "status": "queued", "owner_pid": os.getpid()}, handle)
            except FileExistsError: raise ModelingError("modeling_busy", "one Modeling task is already running", 409)
            self._write_json_atomic(self._path(run_id), row); return row
    def update(self, run_id: str, **values: Any) -> dict[str, Any]:
        with self._mutex:
            row = self.get(run_id) or {}; row.update(values, updated_at_utc=_now()); self._write_json_atomic(self._path(run_id), row)
            active = self.active()
            if row.get("status") in {"completed", "failed", "cancelled", "interrupted"} and active and active.get("run_id") == run_id: self.lock.unlink(missing_ok=True)
            elif active and active.get("run_id") == run_id: self._write_json_atomic(self.lock, {"run_id": run_id, "status": row.get("status"), "owner_pid": row.get("owner_pid", os.getpid())})
            return row
    def cancel(self, run_id: str) -> dict[str, Any]:
        row = self.get(run_id)
        if not row: raise ModelingError("run_not_found", run_id, 404)
        status = str(row.get("status") or "")
        if status in {"completed", "failed", "cancelled", "interrupted"}:
            return row
        if status == "queued":
            return self.update(run_id, status="cancelled", cancel_requested=True, error_code="cancelled_before_fit")
        process = self._workers.get(run_id)
        if process is not None and process.is_alive():
            process.terminate()
            process.join(timeout=2)
            if not process.is_alive():
                return self.update(run_id, status="cancelled", cancel_requested=True, error_code="cancelled_by_user",
                                   result_discarded=True, owner_terminated=True)
            return self.update(run_id, cancel_requested=True, error_code="cancellation_pending_owner_exit")
        if process is not None:
            return self.update(run_id, status="cancelled", cancel_requested=True,
                               error_code="cancelled_after_owner_exit", result_discarded=True,
                               owner_terminated=False)
        requested = self.update(run_id, cancel_requested=True)
        owner_pid = int(requested.get("owner_pid") or 0)
        if process is None and owner_pid > 0 and owner_pid != os.getpid() and status in {"running", "recovering"}:
            try:
                os.kill(owner_pid, signal.SIGTERM)
                for _ in range(20):
                    if not _pid_alive(owner_pid):
                        return self.update(run_id, status="cancelled", error_code="cancelled_by_user",
                                           result_discarded=True, owner_terminated=True)
                    time.sleep(0.1)
            except OSError:
                pass
        return requested

    def restart(self, run_id: str) -> dict[str, Any]:
        row = self.get(run_id)
        if not row: raise ModelingError("run_not_found", run_id, 404)
        if row.get("status") not in {"interrupted", "failed"}: raise ModelingError("run_not_restartable", "only interrupted or failed runs can restart", 409)
        with self._mutex:
            self._ensure_dirs()
            active = self.active()
            if active and active.get("run_id") != run_id and active.get("status") in {"queued", "running", "recovering"}:
                raise ModelingError("modeling_busy", "one Modeling task is already running", 409, {"run_id": active.get("run_id")})
            try:
                fd = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump({"run_id": run_id, "status": "recovering", "owner_pid": os.getpid()}, handle)
            except FileExistsError:
                raise ModelingError("modeling_busy", "one Modeling task is already running", 409)
            row = self.update(run_id, status="recovering", cancel_requested=False, error_code=None, owner_pid=os.getpid())
        if row.get("model_id") == "comparison":
            self.start_process(run_id, "comparison", row.get("dataset") or {}, row.get("model_ids") or [], row.get("parameters") or {})
        elif row.get("operation") == "optimization":
            self.start_process(run_id, "optimization", row.get("dataset") or {}, row["model_id"],
                               {"search_space": row.get("search_space") or {}, "fixed_parameters": row.get("parameters") or {}},
                               int(row.get("budget", 20)), int(row.get("seed", 0)))
        else:
            self.start_process(run_id, "run", row.get("dataset") or {}, row["model_id"], row.get("parameters") or {})
        return row

    def mark_orphaned(self) -> dict[str, Any] | None:
        active = self.active()
        if not active: return None
        run_id = str(active.get("run_id"))
        tracked = self._workers.get(run_id)
        if tracked is not None and not tracked.is_alive():
            row = self.get(run_id)
            if row and row.get("status") in {"queued", "running", "recovering"}:
                return self.update(run_id, status="interrupted", error_code="compute_owner_exited",
                                   error_message="compute process exited before completing; frozen input remains restartable")
            if row and row.get("status") in {"completed", "failed", "cancelled", "interrupted"}:
                self.lock.unlink(missing_ok=True)
            return row
        owner_pid = int(active.get("owner_pid") or 0)
        if owner_pid == os.getpid():
            return None
        if owner_pid > 0 and _pid_alive(owner_pid):
            return None
        row = self.get(str(active.get("run_id")))
        if row and row.get("status") in {"queued", "running", "recovering"}:
            return self.update(row["run_id"], status="interrupted", error_code="service_restarted", error_message="execution owner was interrupted; frozen input remains available for restart")
        if row and row.get("status") in {"completed", "failed", "cancelled", "interrupted"}:
            self.lock.unlink(missing_ok=True)
        return row

    def cleanup(self, *, now_epoch: float | None = None, retention_seconds: int = 24 * 3600, pressure: bool = False) -> dict[str, Any]:
        now_epoch = now_epoch or time.time(); removed = []
        for path in self.runs.glob("modeling_*.json"):
            row = json.loads(path.read_text(encoding="utf-8"))
            if not row or row.get("status") not in {"completed", "cancelled", "failed", "interrupted"}: continue
            if not pressure and now_epoch - path.stat().st_mtime < retention_seconds: continue
            if self.active() and self.active().get("run_id") == row.get("run_id"): continue
            path.unlink(missing_ok=True); removed.append(row.get("run_id"))
        return {"removed_run_ids": removed, "removed_count": len(removed)}


def run_in_store_process(root: str, run_id: str, dataset: Mapping[str, Any], model_id: str, parameters: Mapping[str, Any]) -> None:
    store = ModelingRunStore(Path(root))
    store.update(run_id, owner_pid=os.getpid())
    run_in_store(store, run_id, dataset, model_id, parameters)


def run_comparison_in_store_process(root: str, run_id: str, dataset: Mapping[str, Any], model_ids: Sequence[str], parameters: Mapping[str, Mapping[str, Any]]) -> None:
    store = ModelingRunStore(Path(root))
    store.update(run_id, owner_pid=os.getpid())
    run_comparison_in_store(store, run_id, dataset, model_ids, parameters)


def run_optimization_in_store_process(root: str, run_id: str, dataset: Mapping[str, Any], model_id: str, search_space: Mapping[str, Sequence[Any]], budget: int, seed: int, fixed_parameters: Mapping[str, Any] | None = None) -> None:
    store = ModelingRunStore(Path(root))
    store.update(run_id, owner_pid=os.getpid())
    run_optimization_in_store(store, run_id, dataset, model_id, search_space, budget, seed, fixed_parameters)


def run_in_store(store: ModelingRunStore, run_id: str, dataset: Mapping[str, Any], model_id: str, parameters: Mapping[str, Any] | None = None) -> None:
    try:
        current = store.get(run_id) or {}
        if current.get("status") == "cancelled" or current.get("cancel_requested"):
            return store.update(run_id, status="cancelled", error_code="cancelled_before_fit")
        store.update(run_id, status="running", started_at_utc=_now())
        if (store.get(run_id) or {}).get("cancel_requested"): return store.update(run_id, status="cancelled", error_code="cancelled_before_fit")
        result = fit_model(model_id, dataset, parameters=parameters)
        if (store.get(run_id) or {}).get("cancel_requested"):
            return store.update(run_id, status="cancelled", error_code="cancelled_after_fit", result_discarded=True)
        store.update(run_id, status="completed", completed_at_utc=_now(), dataset=dataset, result=result, result_digest=digest(result),
                     error_code=None, error_message=None, error_detail=None)
    except ModelingError as exc:
        store.update(run_id, status="failed", error_code=exc.code, error_message=exc.message, error_detail=exc.detail)
    except Exception as exc:
        store.update(run_id, status="failed", error_code="internal_modeling_error", error_message=str(exc))


def run_comparison_in_store(store: ModelingRunStore, run_id: str, dataset: Mapping[str, Any], model_ids: Sequence[str], parameters: Mapping[str, Mapping[str, Any]] | None = None) -> None:
    try:
        current = store.get(run_id) or {}
        if current.get("status") == "cancelled" or current.get("cancel_requested"):
            return store.update(run_id, status="cancelled", error_code="cancelled_before_fit")
        store.update(run_id, status="running", started_at_utc=_now())
        if (store.get(run_id) or {}).get("cancel_requested"):
            return store.update(run_id, status="cancelled", error_code="cancelled_before_fit")
        result = compare_models(model_ids, dataset, parameters=parameters)
        if (store.get(run_id) or {}).get("cancel_requested"):
            return store.update(run_id, status="cancelled", error_code="cancelled_after_fit", result_discarded=True)
        store.update(run_id, status="completed", completed_at_utc=_now(), dataset=dataset, result=result, result_digest=digest(result),
                     error_code=None, error_message=None, error_detail=None)
    except ModelingError as exc:
        store.update(run_id, status="failed", error_code=exc.code, error_message=exc.message, error_detail=exc.detail)
    except Exception as exc:
        store.update(run_id, status="failed", error_code="internal_modeling_error", error_message=str(exc))


def run_optimization_in_store(store: ModelingRunStore, run_id: str, dataset: Mapping[str, Any], model_id: str, search_space: Mapping[str, Sequence[Any]], budget: int, seed: int, fixed_parameters: Mapping[str, Any] | None = None) -> None:
    try:
        current = store.get(run_id) or {}
        if current.get("status") == "cancelled" or current.get("cancel_requested"):
            return store.update(run_id, status="cancelled", error_code="cancelled_before_fit")
        store.update(run_id, status="running", started_at_utc=_now())
        if (store.get(run_id) or {}).get("cancel_requested"):
            return store.update(run_id, status="cancelled", error_code="cancelled_before_fit")
        result = auto_optimize(model_id, dataset, search_space=search_space, budget=budget, seed=seed, fixed_parameters=fixed_parameters)
        if (store.get(run_id) or {}).get("cancel_requested"):
            return store.update(run_id, status="cancelled", error_code="cancelled_after_fit", result_discarded=True)
        store.update(run_id, status="completed", completed_at_utc=_now(), dataset=dataset, result=result, result_digest=digest(result),
                     error_code=None, error_message=None, error_detail=None)
    except ModelingError as exc:
        store.update(run_id, status="failed", error_code=exc.code, error_message=exc.message, error_detail=exc.detail)
    except Exception as exc:
        store.update(run_id, status="failed", error_code="internal_modeling_error", error_message=str(exc))


def export_run(run: Mapping[str, Any], destination: Path) -> dict[str, Any]:
    destination = Path(destination); destination.mkdir(parents=True, exist_ok=True)
    (destination / "model_config.json").write_text(json.dumps(run.get("spec"), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    dataset = run.get("dataset") or {}; result = run.get("result") or {}
    (destination / "frozen_input.json").write_text(json.dumps(dataset, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (destination / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    with (destination / "input_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle); writer.writerow(["row_count", "raw_row_count", "columns", "input_digest"]); writer.writerow([dataset.get("row_count"), dataset.get("raw_row_count"), ",".join(dataset.get("columns", [])), dataset.get("input_digest")])
    with (destination / "predictions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        output = result.get("output") or {}
        targets = list(output.get("target_columns") or [])
        identities = list(output.get("row_identity") or [])
        identity_fields = ["entity_id", "listing_id"] if identities else []
        writer.writerow(["prediction_origin", "target_date", "output_kind", *identity_fields, *targets])
        for index, (origin, target, value) in enumerate(zip(output.get("origin_dates", []), output.get("target_dates", []), output.get("values", []))):
            identity = identities[index] if index < len(identities) else {}
            row_identity = [identity.get(field) for field in identity_fields]
            writer.writerow([origin, target, output.get("kind"), *row_identity, *(value if isinstance(value, list) else [value])])
    (destination / "report.md").write_text("# FinancialResearch Modeling Run\n\n" + json.dumps({"run_id": run.get("run_id"), "status": run.get("status"), "result": result}, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return {"destination": str(destination), "files": sorted(p.name for p in destination.iterdir()), "export_digest": digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in destination.iterdir()})}
