from pathlib import Path
from typing import Any, Dict, List, Optional

from services.period_service import period_sort_tuple
from utils.file_utils import load_json_file


MATCH_LEVEL_SCORE = {
    "符合": 3,
    "部分符合": 2,
    "明显偏离": 1,
    "信息不足": 0,
}


def _analysis_dir(company_folder: str | Path) -> Path:
    company_folder = Path(company_folder)
    path = company_folder / "年报分析"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_load_json(path: Path) -> dict:
    try:
        return load_json_file(path)
    except Exception:
        return {}


def get_forecast_check_files(company_folder: str | Path) -> List[Path]:
    folder = _analysis_dir(company_folder)
    return sorted(folder.glob("forecast_check_*.json"))


def get_actual_metrics_registry_path(company_folder: str | Path) -> Path:
    return _analysis_dir(company_folder) / "actual_metrics_registry.json"


def load_all_forecast_checks(company_folder: str | Path) -> List[dict]:
    files = get_forecast_check_files(company_folder)
    rows = []
    for path in files:
        data = _safe_load_json(path)
        if data:
            data["_file_path"] = str(path)
            rows.append(data)
    return rows


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _deviation_pct_display(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return value * 100.0


def build_backtest_overview_rows(company_folder: str | Path) -> List[dict]:
    checks = load_all_forecast_checks(company_folder)
    rows = []

    for item in checks:
        deviation_pct = _safe_float(item.get("deviation_pct"))
        rows.append({
            "generated_at": item.get("generated_at", ""),
            "company_name": item.get("company_name", ""),
            "metric_name": item.get("metric_name", ""),
            "forecast_as_of_period": item.get("forecast_as_of_period", ""),
            "forecast_target_period": item.get("forecast_target_period", ""),
            "actual_observation_period": item.get("actual_observation_period", ""),
            "actual_document_type": item.get("actual_document_type", ""),
            "comparison_basis": item.get("comparison_basis", ""),
            "snapshot_used": item.get("snapshot_used", False),
            "prediction_match_level": item.get("prediction_match_level", ""),
            "prediction_match_score": MATCH_LEVEL_SCORE.get(item.get("prediction_match_level", ""), 0),
            "actual_current_value": _safe_float(item.get("actual_current_value")),
            "expected_current_value": _safe_float(item.get("expected_current_value")),
            "snapshot_base_value": _safe_float(item.get("snapshot_base_value")),
            "snapshot_bull_value": _safe_float(item.get("snapshot_bull_value")),
            "snapshot_bear_value": _safe_float(item.get("snapshot_bear_value")),
            "deviation_abs": _safe_float(item.get("deviation_abs")),
            "deviation_pct": deviation_pct,
            "deviation_pct_display": _deviation_pct_display(deviation_pct),
            "summary": item.get("summary", ""),
            "_file_path": item.get("_file_path", ""),
        })

    rows.sort(
        key=lambda x: (
            x.get("forecast_target_period", ""),
            x.get("actual_observation_period", ""),
            x.get("metric_name", ""),
            x.get("generated_at", ""),
        )
    )
    return rows


def build_backtest_matrix(rows: List[dict]) -> List[dict]:
    grouped: Dict[tuple, Dict[str, Any]] = {}

    for row in rows:
        key = (
            row.get("forecast_target_period", ""),
            row.get("actual_observation_period", ""),
        )
        grouped.setdefault(key, {
            "forecast_target_period": row.get("forecast_target_period", ""),
            "actual_observation_period": row.get("actual_observation_period", ""),
        })

        metric = row.get("metric_name", "") or "unknown_metric"
        grouped[key][f"{metric}_match_level"] = row.get("prediction_match_level", "")
        grouped[key][f"{metric}_deviation_pct"] = row.get("deviation_pct_display")
        grouped[key][f"{metric}_actual"] = row.get("actual_current_value")
        grouped[key][f"{metric}_expected"] = row.get("expected_current_value")

    matrix_rows = list(grouped.values())
    matrix_rows.sort(
        key=lambda x: (
            x.get("forecast_target_period", ""),
            x.get("actual_observation_period", ""),
        )
    )
    return matrix_rows


def build_metric_trend_rows(rows: List[dict], metric_name: str) -> List[dict]:
    filtered = [r for r in rows if r.get("metric_name") == metric_name]
    filtered.sort(
        key=lambda x: (
            x.get("forecast_target_period", ""),
            period_sort_tuple(x.get("actual_observation_period", "")),
            x.get("generated_at", ""),
        )
    )
    return filtered


def build_metric_trend_chart_rows(rows: List[dict], metric_name: str) -> List[dict]:
    trend_rows = build_metric_trend_rows(rows, metric_name)
    chart_rows = []

    for row in trend_rows:
        chart_rows.append({
            "x_label": f"{row.get('forecast_target_period', '')} | {row.get('actual_observation_period', '')}",
            "deviation_pct": row.get("deviation_pct_display"),
            "match_score": row.get("prediction_match_score"),
            "actual_value": row.get("actual_current_value"),
            "expected_value": row.get("expected_current_value"),
        })
    return chart_rows


def build_target_period_summary(rows: List[dict]) -> List[dict]:
    grouped: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        target = row.get("forecast_target_period", "") or "UNKNOWN"
        grouped.setdefault(target, {
            "forecast_target_period": target,
            "record_count": 0,
            "metrics": set(),
            "avg_match_score": 0.0,
            "avg_abs_deviation_pct": 0.0,
            "_score_sum": 0.0,
            "_dev_sum": 0.0,
            "_dev_count": 0,
        })

        grouped[target]["record_count"] += 1
        grouped[target]["metrics"].add(row.get("metric_name", ""))
        grouped[target]["_score_sum"] += row.get("prediction_match_score", 0)

        dev = row.get("deviation_pct_display")
        if dev is not None:
            grouped[target]["_dev_sum"] += abs(dev)
            grouped[target]["_dev_count"] += 1

    results = []
    for target, item in grouped.items():
        count = max(item["record_count"], 1)
        dev_count = max(item["_dev_count"], 1)

        results.append({
            "forecast_target_period": target,
            "record_count": item["record_count"],
            "metric_count": len([m for m in item["metrics"] if m]),
            "metrics": " / ".join(sorted([m for m in item["metrics"] if m])),
            "avg_match_score": round(item["_score_sum"] / count, 3),
            "avg_abs_deviation_pct": round(item["_dev_sum"] / dev_count, 3) if item["_dev_count"] > 0 else None,
        })

    results.sort(key=lambda x: x.get("forecast_target_period", ""))
    return results


def build_backtest_health_summary(rows: List[dict]) -> dict:
    if not rows:
        return {
            "record_count": 0,
            "metric_count": 0,
            "match_distribution": {},
            "avg_abs_deviation_pct": None,
        }

    match_distribution: Dict[str, int] = {}
    metrics = set()
    dev_values = []

    for row in rows:
        lvl = row.get("prediction_match_level", "") or "未知"
        match_distribution[lvl] = match_distribution.get(lvl, 0) + 1

        metric_name = row.get("metric_name", "")
        if metric_name:
            metrics.add(metric_name)

        dev = row.get("deviation_pct_display")
        if dev is not None:
            dev_values.append(abs(dev))

    avg_abs_dev = round(sum(dev_values) / len(dev_values), 3) if dev_values else None

    return {
        "record_count": len(rows),
        "metric_count": len(metrics),
        "match_distribution": match_distribution,
        "avg_abs_deviation_pct": avg_abs_dev,
    }