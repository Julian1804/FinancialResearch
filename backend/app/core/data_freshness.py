"""Small, release-local projection of query-result freshness semantics."""

from __future__ import annotations

from typing import Any


def with_result_freshness(result: dict[str, Any], *, availability_field: str) -> dict[str, Any]:
    """Describe only observations actually returned for the requested Series/interval.

    An empty bounded result does not prove that the Series or Universe has no
    newer observation elsewhere. Operation timestamps belong to the separate
    lifecycle read model, not to this financial-observation projection.
    """
    points = result.get("points") or []
    latest = max((str(row["economic_time"]) for row in points), default=None)
    series = result.get("series") or {}
    result["freshness"] = {
        "scope": "selected_series_returned_interval",
        "series_id": series.get("series_id"),
        "metric_id": result.get("metric_id"),
        "requested_interval": result.get("requested_interval"),
        "latest_observation": {
            "value": latest,
            "status": "available" if latest else "not_proven",
            "basis": "max_economic_time_of_returned_standard_facts" if latest else None,
        },
        "availability": {
            "status": result.get(availability_field),
            "scope": "selected_series_requested_interval",
            "does_not_imply_universe_completeness": True,
        },
    }
    return result
