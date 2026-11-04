"""Bounded release-pinned comparative research over Fund and Equity Series.

This module is intentionally an orchestration seam, not a second data model.
Universe-specific identity, metric, lifecycle, provenance, and physical-read
semantics remain owned by the existing Fund and China Equity query services.
The pure calculations below operate only on the already returned observations.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from backend.app.core.artifact_io import canonical_json
from backend.app.core.china_equity_query import (
    ChinaEquityQueryError,
    ChinaEquityQueryService,
)
from backend.app.core.china_public_fund_query import (
    ChinaPublicFundQueryService,
    FundQueryError,
)
from backend.app.core.serving_release import (
    PinnedServingRelease,
    ServingReleaseError,
    pin_serving_release,
    pin_registered_serving_release,
)


RESEARCH_SCHEMA_VERSION = "fr_comparative_series_research_v1"
RESEARCH_POLICY_VERSION = "comparative_series_v1_policy"
CALCULATION_CONTRACT_VERSION = "comparative_series_calculations_v1"
ALIGNMENT_POLICY = "common_observation_date_intersection"
SUPPORTED_CALCULATIONS = frozenset({
    "rebased_level_index_100",
    "percentage_change",
    "rolling_common_interval_stddev",
    "maximum_drawdown_on_aligned_level_path",
    "pearson_correlation_of_common_interval_percentage_changes",
})
DEFAULT_CALCULATION_SPEC: dict[str, Any] = {
    "rebased_level_index_100": True,
    "percentage_change": True,
    "rolling_common_interval_stddev": {"window": 20},
    "maximum_drawdown_on_aligned_level_path": True,
    "pearson_correlation_of_common_interval_percentage_changes": True,
}

COMPARATIVE_SERIES_V1_POLICY: dict[str, Any] = {
    "policy_id": RESEARCH_POLICY_VERSION,
    "max_selected_series": 8,
    "max_interval_days": 366,
    "minimum_selected_series": 2,
    "supported_series": {
        "Fund": {"subject_type": "fund_share_class", "metric_ids": ["fund.nav", "fund.accumulated_nav"]},
        "Equity": {"subject_type": "listing", "metric_ids": ["equity.close"], "adjustment_basis": ["unadjusted"]},
    },
}


class ComparativeResearchError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ComparativeSeriesSelection:
    """Long-lived research selection; application limits live in policy."""

    universe: str
    subject_type: str
    subject_id: str
    metric_id: str
    adjustment_basis: str | None = None

    @property
    def series_key(self) -> str:
        suffix = f":{self.adjustment_basis}" if self.adjustment_basis else ""
        return f"{self.universe}:{self.subject_type}:{self.subject_id}:{self.metric_id}{suffix}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "universe": self.universe,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "metric_id": self.metric_id,
            "adjustment_basis": self.adjustment_basis,
            "series_key": self.series_key,
        }


@dataclass(frozen=True)
class ComparativeResearchSpec:
    """Research semantics without today's application-size guardrails."""

    selections: tuple[ComparativeSeriesSelection, ...]
    start: str
    end: str
    alignment_policy: str = ALIGNMENT_POLICY
    calculation_spec: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        try:
            start, end = date.fromisoformat(self.start), date.fromisoformat(self.end)
        except ValueError as exc:
            raise ComparativeResearchError("invalid_research_date_range", "start and end must be ISO calendar dates") from exc
        if start > end:
            raise ComparativeResearchError("invalid_research_date_range", "start must not be later than end")
        if not self.selections:
            raise ComparativeResearchError("invalid_series_selection", "at least one Series selection is required")
        if self.alignment_policy != ALIGNMENT_POLICY:
            raise ComparativeResearchError("unsupported_alignment_policy", "Research1 supports common observation-date intersection only")
        keys = [selection.series_key for selection in self.selections]
        if len(set(keys)) != len(keys):
            raise ComparativeResearchError("duplicate_series_selection", "the same Series cannot be selected more than once", 409)

    @property
    def calculation_contract(self) -> dict[str, Any]:
        if self.calculation_spec is None:
            return dict(DEFAULT_CALCULATION_SPEC)
        if isinstance(self.calculation_spec, Mapping):
            return dict(self.calculation_spec)
        return self.calculation_spec  # type: ignore[return-value]

    def as_dict(self) -> dict[str, Any]:
        return {
            "selections": [selection.as_dict() for selection in self.selections],
            "requested_interval": {"start": self.start, "end": self.end},
            "alignment_policy": self.alignment_policy,
            "calculation_spec": self.calculation_contract,
        }


def policy_descriptor() -> dict[str, Any]:
    return {
        "schema_version": RESEARCH_SCHEMA_VERSION,
        "policy": COMPARATIVE_SERIES_V1_POLICY,
        "alignment_policy": ALIGNMENT_POLICY,
        "calculation_contract_version": CALCULATION_CONTRACT_VERSION,
    }


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ComparativeResearchError("non_numeric_observation", "a research input observation is not numeric", 409) from exc
    if not result.is_finite():
        raise ComparativeResearchError("non_numeric_observation", "a research input observation is not finite", 409)
    return result


def _number(value: Decimal | float | int | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _decimal_text(value: Any) -> str:
    result = _decimal(value).normalize()
    return format(result, "f")


def _validated_calculation_spec(calculation_spec: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return the mandatory-output Research1 calculation contract.

    Research1 deliberately has one calculation family.  Boolean fields are
    retained as an explicit contract surface, but disabling a mandatory output
    is rejected instead of being silently ignored.
    """
    if calculation_spec is None:
        spec = dict(DEFAULT_CALCULATION_SPEC)
    elif not isinstance(calculation_spec, Mapping):
        raise ComparativeResearchError("invalid_calculation_parameter", "calculation_spec must be an object")
    else:
        spec = dict(calculation_spec)
    unknown = sorted(set(spec) - SUPPORTED_CALCULATIONS)
    if unknown:
        raise ComparativeResearchError("unsupported_calculation", f"unsupported Research1 calculation: {unknown[0]}")
    mandatory = SUPPORTED_CALCULATIONS - {"rolling_common_interval_stddev"}
    for key in sorted(mandatory):
        if key not in spec:
            continue
        if not isinstance(spec[key], bool):
            raise ComparativeResearchError("invalid_calculation_parameter", f"{key} must be true for Research1 mandatory output")
        if not spec[key]:
            raise ComparativeResearchError("calculation_disabled", f"Research1 requires {key}; disabling it is unsupported")
    rolling = spec.get("rolling_common_interval_stddev", {"window": 20})
    if rolling is False:
        raise ComparativeResearchError("calculation_disabled", "Research1 requires rolling_common_interval_stddev; disabling it is unsupported")
    if rolling is True:
        rolling = {"window": 20}
    if not isinstance(rolling, Mapping):
        raise ComparativeResearchError("invalid_calculation_parameter", "rolling_common_interval_stddev must be an object with window")
    window = rolling.get("window", 20)
    if isinstance(window, bool) or not isinstance(window, int):
        raise ComparativeResearchError("invalid_calculation_parameter", "rolling common-interval window must be an integer")
    if window < 2 or window > 366:
        raise ComparativeResearchError("invalid_calculation_parameter", "rolling common-interval window must be between 2 and 366")
    normalized = {key: True for key in sorted(mandatory)}
    normalized["rolling_common_interval_stddev"] = {"window": window}
    return normalized


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _normalize_point(selection: ComparativeSeriesSelection, point: Mapping[str, Any]) -> dict[str, Any]:
    economic_time = str(point.get("economic_time") or "")
    if not economic_time:
        raise ComparativeResearchError("invalid_observation_time", "a research observation has no economic_time", 409)
    try:
        date.fromisoformat(economic_time)
    except ValueError as exc:
        raise ComparativeResearchError("invalid_observation_time", "research observations require ISO calendar dates", 409) from exc
    if point.get("value") is None:
        raise ComparativeResearchError("non_numeric_observation", "a research observation has no value", 409)
    source = point.get("source")
    if source is None and point.get("source_observation_id") is not None:
        source = {"source_observation_id": point.get("source_observation_id")}
    return {
        "economic_time": economic_time,
        "value": point.get("value"),
        "unit": point.get("unit"),
        "currency": point.get("currency"),
        "scale": point.get("scale"),
        "time_role": point.get("time_role"),
        "provenance": source or {},
    }


def align_observations(
    selections: Sequence[ComparativeSeriesSelection],
    observations: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Align by exact observed dates without filling, interpolation, or zeros."""
    by_series: dict[str, dict[str, dict[str, Any]]] = {}
    for selection in selections:
        key = selection.series_key
        dates: dict[str, dict[str, Any]] = {}
        for point in observations.get(key, ()):
            normalized = _normalize_point(selection, point)
            if normalized["economic_time"] in dates:
                raise ComparativeResearchError(
                    "duplicate_observation_date",
                    f"Series {key} has more than one observation on {normalized['economic_time']}",
                    409,
                )
            dates[normalized["economic_time"]] = normalized
        by_series[key] = dates
    common_dates = sorted(set.intersection(*(set(values) for values in by_series.values()))) if by_series else []
    excluded = {
        key: sorted(set(values) - set(common_dates))
        for key, values in by_series.items()
    }
    aligned_inputs = [
        {
            "economic_time": economic_time,
            "observations": [
                {"series_key": selection.series_key, **by_series[selection.series_key][economic_time]}
                for selection in selections
            ],
        }
        for economic_time in common_dates
    ]
    return {
        "status": "available" if common_dates else "no_common_observations",
        "common_dates": common_dates,
        "common_observation_count": len(common_dates),
        "excluded_dates_by_series": excluded,
        "observations_by_series": {
            key: [values[date_key] for date_key in sorted(values)]
            for key, values in by_series.items()
        },
        "aligned_inputs": aligned_inputs,
        "series_observation_counts": {key: len(values) for key, values in by_series.items()},
    }


def _series_values(aligned_inputs: Sequence[Mapping[str, Any]], key: str) -> list[tuple[str, Decimal]]:
    values: list[tuple[str, Decimal]] = []
    for row in aligned_inputs:
        observation = next(item for item in row["observations"] if item["series_key"] == key)
        values.append((str(row["economic_time"]), _decimal(observation["value"])))
    return values


def _percentage_changes(values: Sequence[tuple[str, Decimal]]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for previous, current in zip(values, values[1:]):
        if previous[1] == 0:
            raise ComparativeResearchError("zero_change_denominator", "percentage change cannot use a zero previous level", 409)
        change = current[1] / previous[1] - Decimal(1)
        changes.append({
            "from_date": previous[0],
            "to_date": current[0],
            "percentage_change": _number(change),
            "percentage_change_decimal": _decimal_text(change),
        })
    return changes


def _sample_stddev(values: Sequence[Decimal]) -> Decimal | None:
    if len(values) < 2:
        return None
    mean = sum(values, Decimal(0)) / Decimal(len(values))
    variance = sum((value - mean) ** 2 for value in values) / Decimal(len(values) - 1)
    return variance.sqrt()


def _correlation(left: Sequence[Decimal], right: Sequence[Decimal]) -> Decimal | None:
    if len(left) < 2 or len(left) != len(right):
        return None
    left_mean = sum(left, Decimal(0)) / Decimal(len(left))
    right_mean = sum(right, Decimal(0)) / Decimal(len(right))
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_sum = sum((a - left_mean) ** 2 for a in left)
    right_sum = sum((b - right_mean) ** 2 for b in right)
    denominator = (left_sum * right_sum).sqrt()
    if denominator == 0:
        return None
    return numerator / denominator


def calculate_comparative_metrics(
    selections: Sequence[ComparativeSeriesSelection],
    alignment: Mapping[str, Any],
    calculation_spec: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Pure calculation layer; it performs no reads or release operations."""
    spec = _validated_calculation_spec(calculation_spec)
    window = int(spec["rolling_common_interval_stddev"]["window"])

    aligned_inputs = list(alignment["aligned_inputs"])
    keys = [selection.series_key for selection in selections]
    values = {key: _series_values(aligned_inputs, key) for key in keys}
    changes = {key: _percentage_changes(values[key]) for key in keys} if aligned_inputs else {key: [] for key in keys}
    common_count = len(aligned_inputs)

    rebased: dict[str, Any] = {}
    for key in keys:
        path = []
        if values[key]:
            first = values[key][0][1]
            if first == 0:
                rebased[key] = {"status": "zero_initial_level", "points": []}
                continue
            path = [
                {"economic_time": economic_time, "rebased_level_index_100": _number(value / first * Decimal(100))}
                for economic_time, value in values[key]
            ]
            rebased[key] = {"status": "available", "points": path}
        else:
            rebased[key] = {"status": "no_common_observations", "points": []}

    change_semantics = {
        key: (
            "nav_percentage_change" if selection.metric_id == "fund.nav"
            else "accumulated_nav_percentage_change" if selection.metric_id == "fund.accumulated_nav"
            else "unadjusted_price_percentage_change"
        )
        for key, selection in ((selection.series_key, selection) for selection in selections)
    }
    percentage_result = {
        key: {"status": "available" if changes[key] else "insufficient_common_intervals", "change_semantics": change_semantics[key], "points": changes[key]}
        for key in keys
    }

    rolling_result: dict[str, Any] = {}
    for key in keys:
        change_values = [_decimal(item["percentage_change_decimal"]) for item in changes[key]]
        if len(change_values) < window:
            rolling_result[key] = {"status": "insufficient_common_intervals", "window": window, "value": None}
        else:
            value = _sample_stddev(change_values[-window:])
            rolling_result[key] = {
                "status": "available", "window": window,
                "value": _number(value), "value_decimal": _decimal_text(value),
                "semantics": "sample_stddev_of_latest_common_interval_percentage_changes_non_annualized",
            }

    drawdown_result: dict[str, Any] = {}
    for key in keys:
        if not values[key]:
            drawdown_result[key] = {"status": "no_common_observations", "value": None}
            continue
        peak = values[key][0][1]
        worst = Decimal(0)
        for _, value in values[key]:
            peak = max(peak, value)
            if peak != 0:
                worst = min(worst, value / peak - Decimal(1))
        drawdown_result[key] = {
            "status": "available", "value": _number(worst), "value_decimal": _decimal_text(worst),
            "semantics": "maximum_drawdown_on_aligned_level_path",
        }

    correlation_matrix: dict[str, dict[str, Any]] = {}
    for left in keys:
        correlation_matrix[left] = {}
        left_values = [_decimal(item["percentage_change_decimal"]) for item in changes[left]]
        for right in keys:
            right_values = [_decimal(item["percentage_change_decimal"]) for item in changes[right]]
            value = _correlation(left_values, right_values)
            correlation_matrix[left][right] = {
                "status": "available" if value is not None else "insufficient_or_zero_variance",
                "value": _number(value),
                "value_decimal": _decimal_text(value) if value is not None else None,
            }

    if common_count == 0:
        result_status = "no_common_observations"
    elif common_count < 2:
        result_status = "insufficient_common_intervals"
    else:
        result_status = "available"
    return {
        "status": result_status,
        "calculation_contract_version": CALCULATION_CONTRACT_VERSION,
        "rebased_level_index_100": rebased,
        "percentage_change": percentage_result,
        "rolling_common_interval_stddev": rolling_result,
        "maximum_drawdown_on_aligned_level_path": drawdown_result,
        "pearson_correlation_of_common_interval_percentage_changes": {
            "status": "available" if common_count >= 2 else "insufficient_common_intervals",
            "matrix": correlation_matrix,
        },
    }


def _release_identity(release: PinnedServingRelease) -> dict[str, Any]:
    if release.release_type != "composite_serving_release" or not release.release_id:
        raise ComparativeResearchError("research_release_unavailable", "Research1 requires one registered composite serving release", 503)
    return {
        "release_id": release.release_id,
        "release_hash": release.release_hash,
        "snapshot_id": release.snapshot_id,
        "database_generation_id": release.database_generation_id,
        "read_model_release_id": release.read_model_release_id,
        "read_model_release_hash": release.read_model_release_hash,
        "components": [
            {
                "component_id": row.get("component_id"),
                "snapshot_id": row.get("snapshot_id"),
                "manifest_sha256": row.get("manifest_sha256"),
                "database_generation_id": row.get("database_generation_id"),
            }
            for row in release.component_bindings
        ],
    }


def _validate_application_policy(spec: ComparativeResearchSpec) -> dict[str, Any]:
    policy = COMPARATIVE_SERIES_V1_POLICY
    count = len(spec.selections)
    if count < int(policy["minimum_selected_series"]) or count > int(policy["max_selected_series"]):
        raise ComparativeResearchError(
            "research_policy_series_limit",
            f"{RESEARCH_POLICY_VERSION} supports {policy['minimum_selected_series']} to {policy['max_selected_series']} selected Series",
        )
    start, end = date.fromisoformat(spec.start), date.fromisoformat(spec.end)
    if (end - start).days > int(policy["max_interval_days"]):
        raise ComparativeResearchError(
            "research_policy_interval_limit",
            f"{RESEARCH_POLICY_VERSION} supports intervals no longer than {policy['max_interval_days']} days",
        )
    for selection in spec.selections:
        supported = policy["supported_series"].get(selection.universe)
        if supported is None or selection.subject_type != supported["subject_type"] or selection.metric_id not in supported["metric_ids"]:
            raise ComparativeResearchError("unsupported_research_series", f"{selection.series_key} is outside Research1 scope")
        if selection.universe == "Equity" and selection.adjustment_basis != "unadjusted":
            raise ComparativeResearchError("unsupported_adjustment_basis", "Research1 supports only unadjusted Equity close")
        if selection.universe == "Fund" and selection.adjustment_basis is not None:
            raise ComparativeResearchError("invalid_adjustment_basis", "Fund selections must not specify an adjustment basis")
    return {
        "policy_id": RESEARCH_POLICY_VERSION,
        "max_selected_series": policy["max_selected_series"],
        "max_interval_days": policy["max_interval_days"],
        "selected_series_count": count,
        "requested_interval_days": (end - start).days,
    }


def _check_release_metadata(release: PinnedServingRelease, metadata: Mapping[str, Any], universe: str) -> None:
    expected = {
        "release_id": release.release_id,
        "release_hash": release.release_hash,
        "database_generation_id": release.database_generation_id,
    }
    try:
        component_id = {"Fund": "CN_PUBLIC_FUND", "Equity": "CN_A_SHARE"}.get(universe, universe)
        component_snapshot_id = str(release.component(component_id).get("snapshot_id") or "")
    except (KeyError, ServingReleaseError):
        component_snapshot_id = ""
    allowed_snapshots = {str(release.snapshot_id)}
    if component_snapshot_id:
        allowed_snapshots.add(component_snapshot_id)
    if any(metadata.get(key) != value for key, value in expected.items()) or str(metadata.get("snapshot_id") or "") not in allowed_snapshots:
        raise ComparativeResearchError("research_release_binding_mismatch", f"{universe} service did not retain the pinned release identity", 409)


def _registered_release_provenance(release: PinnedServingRelease) -> dict[str, Any]:
    """Establish registry membership without treating an object as proof."""
    if not release.release_id or not release.release_hash:
        return {
            "requeryable_from_registered_release": False,
            "requeryability_basis": "release_identity_incomplete",
            "requeryability_scope": "execution_time_only",
        }
    try:
        registered = pin_registered_serving_release(release.release_id, release.release_hash)
    except (OSError, ValueError, ServingReleaseError):
        return {
            "requeryable_from_registered_release": False,
            "requeryability_basis": "registered_release_provenance_not_established",
            "requeryability_scope": "execution_time_only",
        }
    matches = registered.release_id == release.release_id and registered.release_hash == release.release_hash
    return {
        "requeryable_from_registered_release": matches,
        "requeryability_basis": "registered_release_registry_match" if matches else "registered_release_identity_mismatch",
        "requeryability_scope": "execution_time_only",
    }


def _csv_export(result: Mapping[str, Any]) -> dict[str, Any]:
    receipt = result["receipt"]
    metadata = [
        ("schema_version", RESEARCH_SCHEMA_VERSION),
        ("run_id", receipt["run_id"]),
        ("release_id", receipt["release"]["release_id"]),
        ("release_hash", receipt["release"]["release_hash"]),
        ("alignment_policy", receipt["alignment_policy"]),
        ("calculation_contract_version", receipt["calculation_contract_version"]),
        ("input_digest", receipt["aligned_input_digest"]),
        ("result_digest", receipt["result_digest"]),
    ]
    aligned = io.StringIO()
    writer = csv.writer(aligned, lineterminator="\n")
    for key, value in metadata:
        writer.writerow([f"# {key}", value])
    writer.writerow(["economic_time", "universe", "subject_type", "subject_id", "series_id", "metric_id", "adjustment_basis", "series_key", "value", "unit", "currency", "scale", "time_role", "provenance_json"])
    bindings = {item["series_key"]: item for item in result["resolved_series_bindings"]}
    for row in result["alignment"]["aligned_inputs"]:
        for observation in row["observations"]:
            binding = bindings[observation["series_key"]]
            writer.writerow([
                row["economic_time"], binding["universe"], binding["subject_type"], binding["subject_id"],
                binding["series_id"], binding["metric_id"], binding["adjustment_basis"], observation["series_key"], observation["value"],
                observation.get("unit"), observation.get("currency"), observation.get("scale"),
                observation.get("time_role"), canonical_json(observation.get("provenance") or {}),
            ])

    observations = io.StringIO()
    observation_writer = csv.writer(observations, lineterminator="\n")
    for key, value in metadata:
        observation_writer.writerow([f"# {key}", value])
    observation_writer.writerow(["economic_time", "universe", "subject_type", "subject_id", "series_id", "metric_id", "adjustment_basis", "series_key", "value", "unit", "currency", "scale", "time_role", "included_in_alignment", "provenance_json"])
    common_dates = set(result["alignment"]["common_dates"])
    for series_key, points in result["alignment"]["observations_by_series"].items():
        binding = bindings[series_key]
        for observation in points:
            observation_writer.writerow([
                observation["economic_time"], binding["universe"], binding["subject_type"], binding["subject_id"],
                binding["series_id"], binding["metric_id"], binding["adjustment_basis"], series_key, observation["value"], observation.get("unit"),
                observation.get("currency"), observation.get("scale"), observation.get("time_role"),
                observation["economic_time"] in common_dates, canonical_json(observation.get("provenance") or {}),
            ])

    calculations = io.StringIO()
    calc_writer = csv.writer(calculations, lineterminator="\n")
    for key, value in metadata:
        calc_writer.writerow([f"# {key}", value])
    calc_writer.writerow(["calculation", "universe", "subject_type", "subject_id", "series_id", "metric_id", "adjustment_basis", "series_key", "from_date", "to_date", "value", "status", "semantics"])
    for series_key, payload in result["calculations"]["percentage_change"].items():
        binding = bindings[series_key]
        for point in payload["points"]:
            calc_writer.writerow(["percentage_change", binding["universe"], binding["subject_type"], binding["subject_id"], binding["series_id"], binding["metric_id"], binding["adjustment_basis"], series_key, point["from_date"], point["to_date"], point["percentage_change"], payload["status"], payload["change_semantics"]])
    for series_key, payload in result["calculations"]["rolling_common_interval_stddev"].items():
        binding = bindings[series_key]
        calc_writer.writerow(["rolling_common_interval_stddev", binding["universe"], binding["subject_type"], binding["subject_id"], binding["series_id"], binding["metric_id"], binding["adjustment_basis"], series_key, "", "", payload.get("value"), payload["status"], payload.get("semantics", "")])
    for series_key, payload in result["calculations"]["maximum_drawdown_on_aligned_level_path"].items():
        binding = bindings[series_key]
        calc_writer.writerow(["maximum_drawdown_on_aligned_level_path", binding["universe"], binding["subject_type"], binding["subject_id"], binding["series_id"], binding["metric_id"], binding["adjustment_basis"], series_key, "", "", payload.get("value"), payload["status"], payload.get("semantics", "")])
    return {
        "aligned_inputs_csv": aligned.getvalue(),
        "observations_csv": observations.getvalue(),
        "calculations_csv": calculations.getvalue(),
        "media_type": "text/csv",
    }


def run_comparative_research(
    spec: ComparativeResearchSpec,
    *,
    release: PinnedServingRelease | None = None,
    equity_service: Any | None = None,
    fund_service: Any | None = None,
) -> dict[str, Any]:
    """Execute one bounded run against one release binding."""
    applied_policy = _validate_application_policy(spec)
    calculation_spec = _validated_calculation_spec(spec.calculation_contract)
    supplied_release = release is not None
    if release is None:
        try:
            release = pin_serving_release()
        except (OSError, ValueError, ServingReleaseError) as exc:
            raise ComparativeResearchError("research_release_unavailable", "the active composite serving release is unavailable", 503) from exc
    release_identity = _release_identity(release)
    if equity_service is None:
        try:
            equity_service = ChinaEquityQueryService.for_release(release)
        except ChinaEquityQueryError as exc:
            raise ComparativeResearchError(exc.code, exc.message, exc.status_code) from exc
    if fund_service is None:
        try:
            component = release.component("CN_PUBLIC_FUND")
            fund_service = ChinaPublicFundQueryService.for_binding(
                access_mode="release",
                snapshot_id=release.snapshot_id,
                manifest_sha256=str(component.get("manifest_sha256") or ""),
                release=release,
            )
        except (FundQueryError, ServingReleaseError) as exc:
            code = getattr(exc, "code", "research_fund_binding_unavailable")
            message = getattr(exc, "message", str(exc))
            status = getattr(exc, "status_code", 503)
            raise ComparativeResearchError(code, message, status) from exc
    _check_release_metadata(release, equity_service.snapshot_metadata(), "Equity")
    _check_release_metadata(release, fund_service.snapshot_metadata(), "Fund")

    observations: dict[str, list[dict[str, Any]]] = {}
    series_results: list[dict[str, Any]] = []
    resolved_series_bindings: list[dict[str, Any]] = []
    fund_requests: list[tuple[ComparativeSeriesSelection, dict[str, Any]]] = []
    for selection in spec.selections:
        if selection.universe == "Fund":
            fund_requests.append((selection, {
                "subject_type": selection.subject_type,
                "subject_id": selection.subject_id,
                "metric_id": selection.metric_id,
                "start": spec.start,
                "end": spec.end,
                "max_rows": 50_000,
            }))
    fund_payloads: dict[str, Mapping[str, Any]] = {}
    if fund_requests:
        try:
            batch = fund_service.batch_time_series([request for _, request in fund_requests])
        except FundQueryError as exc:
            raise ComparativeResearchError(exc.code, exc.message, exc.status_code) from exc
        fund_payloads = {
            selection.series_key: payload
            for (selection, _), payload in zip(fund_requests, batch.get("results", []))
        }
        if len(fund_payloads) != len(fund_requests) or int(batch.get("result_count") or 0) != len(fund_requests):
            raise ComparativeResearchError("fund_batch_result_mismatch", "Fund batch returned an incomplete result set", 503)

    for selection in spec.selections:
        try:
            if selection.universe == "Fund":
                payload = fund_payloads[selection.series_key]
            else:
                payload = equity_service.time_series(
                    listing_id=selection.subject_id,
                    metric_id=selection.metric_id,
                    adjustment_basis=str(selection.adjustment_basis),
                    start=spec.start,
                    end=spec.end,
                    max_rows=5_000,
                )
        except (FundQueryError, ChinaEquityQueryError) as exc:
            raise ComparativeResearchError(exc.code, exc.message, exc.status_code) from exc
        points = [dict(point) for point in payload.get("points", [])]
        resolved_series = payload.get("series") or {}
        series_id = str(resolved_series.get("series_id") or "")
        if not series_id:
            raise ComparativeResearchError(
                "series_identity_unavailable",
                f"{selection.series_key} did not return a durable Series identity from its Universe owner",
                503,
            )
        resolved_binding = {
            "universe": selection.universe,
            "subject_type": selection.subject_type,
            "subject_id": selection.subject_id,
            "series_id": series_id,
            "metric_id": selection.metric_id,
            "adjustment_basis": selection.adjustment_basis,
            "series_key": selection.series_key,
        }
        resolved_series_bindings.append(resolved_binding)
        observations[selection.series_key] = points
        series_results.append({
            "selection": selection.as_dict(),
            "resolved_series_binding": resolved_binding,
            "query_status": payload.get("data_state") or payload.get("status"),
            "row_count": int(payload.get("row_count") or 0),
            "subject": payload.get("subject"),
            "series": payload.get("series"),
            "coverage": payload.get("coverage"),
            "access": payload.get("access"),
            "observed_dates": sorted(str(point.get("economic_time")) for point in points),
        })

    alignment = align_observations(spec.selections, observations)
    calculations = calculate_comparative_metrics(spec.selections, alignment, calculation_spec)
    aligned_input_digest = _digest({
        "schema_version": RESEARCH_SCHEMA_VERSION,
        "alignment_policy": spec.alignment_policy,
        "selections": [selection.as_dict() for selection in spec.selections],
        "resolved_series_bindings": resolved_series_bindings,
        "aligned_inputs": alignment["aligned_inputs"],
    })
    result_digest = _digest({
        "calculation_contract_version": CALCULATION_CONTRACT_VERSION,
        "calculation_spec": calculation_spec,
        "calculations": calculations,
    })
    requeryability = _registered_release_provenance(release)
    receipt_without_run_id = {
        "schema_version": "fr_research_run_receipt_v1",
        "release": release_identity,
        "selections": [selection.as_dict() for selection in spec.selections],
        "requested_interval": {"start": spec.start, "end": spec.end},
        "aligned_interval": {
            "start": alignment["common_dates"][0] if alignment["common_dates"] else None,
            "end": alignment["common_dates"][-1] if alignment["common_dates"] else None,
        },
        "alignment_policy": spec.alignment_policy,
        "calculation_contract_version": CALCULATION_CONTRACT_VERSION,
        "calculation_spec": calculation_spec,
        "application_policy": applied_policy,
        "resolved_series_bindings": resolved_series_bindings,
        "release_binding_origin": "active_registered_release" if not supplied_release else "explicit_release_argument",
        **requeryability,
        "input_observation_counts": alignment["series_observation_counts"],
        "common_observation_count": alignment["common_observation_count"],
        "excluded_dates_by_series": alignment["excluded_dates_by_series"],
        "provenance_references": [
            {
                "series_key": observation["series_key"],
                "economic_time": row["economic_time"],
                "provenance": observation.get("provenance") or {},
            }
            for row in alignment["aligned_inputs"]
            for observation in row["observations"]
        ],
        "aligned_input_digest": aligned_input_digest,
        "result_digest": result_digest,
        "recomputable_from_exported_input": True,
    }
    run_id = f"research_run:{_digest(receipt_without_run_id)[:32]}"
    receipt = {**receipt_without_run_id, "run_id": run_id}
    result = {
        "schema_version": RESEARCH_SCHEMA_VERSION,
        "status": calculations["status"],
        "run_id": run_id,
        "receipt": receipt,
        "release": release_identity,
        "resolved_series_bindings": resolved_series_bindings,
        "series_results": series_results,
        "alignment": alignment,
        "calculations": calculations,
    }
    result["exports"] = _csv_export(result)
    return result
