"""Conservative first-run storage estimates.

This is a planning guard, not a promise of exact download size.  Unknown
source-driven populations are reported as unknown rather than silently
pretending that a tiny sample is the full requirement.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping


MIB = 1024 * 1024
BASE_MIN_BYTES = 512 * MIB
BASE_MAX_BYTES = 2 * 1024 * MIB
SAFETY_FACTOR = 1.25
BYTES_PER_SERIES_DAY_MIN = 1024
BYTES_PER_SERIES_DAY_MAX = 4096
# Peak execution keeps the predecessor and successor together, retains one
# rollback generation, and needs acquisition/checkpoint/materialization and
# derived-serving space.  These components are exposed separately so the UI
# can explain the estimate without pretending to byte precision.
PEAK_COMPONENT_FACTORS = {
    "predecessor": 1.0,
    "successor": 1.0,
    "rollback_retention": 1.0,
    "acquisition_and_recovery": 0.5,
    "materialization_temporary": 0.5,
    "derived_serving": 0.25,
}
UNKNOWN_SERIES_CAPS = {"CN_A_SHARE": 5000, "CN_PUBLIC_FUND": 5000}


def _days(scope: Mapping[str, Any]) -> int:
    if scope.get("full_available_history"):
        return 366
    try:
        start = date.fromisoformat(str(scope["history_start"]))
        end = date.fromisoformat(str(scope["history_end"]))
    except (KeyError, TypeError, ValueError):
        return 366
    return max(1, (end - start).days + 1)


def _series_bounds(scope: Mapping[str, Any]) -> tuple[int, int, bool]:
    spec = scope.get("population_spec") or {}
    selectors = spec.get("selectors")
    if isinstance(selectors, list) and selectors:
        return len(selectors), len(selectors), False
    estimate = spec.get("estimated_series_count")
    if isinstance(estimate, int) and estimate > 0:
        return estimate, estimate, False
    universe = str(scope.get("universe") or "")
    return 1, UNKNOWN_SERIES_CAPS.get(universe, 5000), True


def estimate_storage_requirement(profile: Mapping[str, Any]) -> dict[str, Any]:
    scopes = profile.get("scopes") if isinstance(profile, Mapping) else None
    if not isinstance(scopes, list) or not scopes:
        raise ValueError("a storage estimate requires at least one requested scope")
    rows = []
    minimum = BASE_MIN_BYTES
    maximum = BASE_MAX_BYTES
    uncertain = False
    for scope in scopes:
        if not isinstance(scope, Mapping) or scope.get("state") != "enabled":
            continue
        low_series, high_series, scope_uncertain = _series_bounds(scope)
        days = _days(scope)
        low = low_series * days * BYTES_PER_SERIES_DAY_MIN
        high = high_series * days * BYTES_PER_SERIES_DAY_MAX
        minimum += low
        maximum += high
        uncertain = uncertain or scope_uncertain
        rows.append({
            "universe": scope.get("universe"),
            "requested_days": days,
            "series_lower_bound": low_series,
            "series_upper_bound": high_series,
            "estimated_bytes_lower_bound": low,
            "estimated_bytes_upper_bound": high,
            "population_bound_status": "bounded" if not scope_uncertain else "requires_discovery",
        })
    peak_factor = sum(PEAK_COMPONENT_FACTORS.values())
    required = int(maximum * peak_factor * SAFETY_FACTOR)
    return {
        "schema_version": "fr_storage_capacity_estimate_v1",
        "status": "requires_population_discovery" if uncertain else "bounded",
        "minimum_bytes": int(minimum),
        "maximum_bytes": int(maximum),
        "recommended_free_bytes": required,
        "safety_factor": SAFETY_FACTOR,
        "peak_component_factor": peak_factor,
        "peak_components": PEAK_COMPONENT_FACTORS,
        "assumptions": {
            "base_min_bytes": BASE_MIN_BYTES,
            "base_max_bytes": BASE_MAX_BYTES,
            "bytes_per_series_day_min": BYTES_PER_SERIES_DAY_MIN,
            "bytes_per_series_day_max": BYTES_PER_SERIES_DAY_MAX,
            "unknown_population_caps": UNKNOWN_SERIES_CAPS,
        },
        "scopes": rows,
    }


def capacity_decision(profile: Mapping[str, Any], *, free_bytes: int) -> dict[str, Any]:
    estimate = estimate_storage_requirement(profile)
    enough = int(free_bytes) >= int(estimate["recommended_free_bytes"])
    if not enough:
        decision = "block_insufficient_space"
    elif estimate["status"] == "requires_population_discovery":
        decision = "requires_population_discovery"
    else:
        decision = "allow"
    return {
        **estimate,
        "free_bytes": int(free_bytes),
        "decision": decision,
        "shortfall_bytes": max(0, int(estimate["recommended_free_bytes"]) - int(free_bytes)),
    }
