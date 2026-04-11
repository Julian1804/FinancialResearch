from pathlib import Path
from typing import Any, Dict, List, Optional

from services.backtest_dashboard_service import build_backtest_overview_rows
from services.period_service import period_sort_tuple


MATCH_LEVEL_ORDER = {
    "符合": 3,
    "部分符合": 2,
    "明显偏离": 1,
    "信息不足": 0,
}


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _sign_text(value: Optional[float]) -> str:
    if value is None:
        return "未知"
    if value > 0:
        return "高于预期"
    if value < 0:
        return "低于预期"
    return "与预期基本一致"


def _abs_or_none(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return abs(value)


def _group_by_target(rows: List[dict]) -> Dict[str, List[dict]]:
    grouped: Dict[str, List[dict]] = {}
    for row in rows:
        target = row.get("forecast_target_period", "") or "UNKNOWN"
        grouped.setdefault(target, []).append(row)
    return grouped


def _group_by_metric(rows: List[dict]) -> Dict[str, List[dict]]:
    grouped: Dict[str, List[dict]] = {}
    for row in rows:
        metric = row.get("metric_name", "") or "unknown_metric"
        grouped.setdefault(metric, []).append(row)
    return grouped


def _sort_rows_for_trend(rows: List[dict]) -> List[dict]:
    return sorted(
        rows,
        key=lambda x: (
            x.get("forecast_target_period", ""),
            period_sort_tuple(x.get("actual_observation_period", "")),
            x.get("generated_at", ""),
        )
    )


def _avg(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    values = sorted(values)
    n = len(values)
    if n % 2 == 1:
        return values[n // 2]
    return (values[n // 2 - 1] + values[n // 2]) / 2.0


def build_target_period_retro_summary(rows: List[dict], target_period: str) -> dict:
    target_rows = [r for r in rows if r.get("forecast_target_period", "") == target_period]
    target_rows = _sort_rows_for_trend(target_rows)

    if not target_rows:
        return {
            "forecast_target_period": target_period,
            "summary_text": f"{target_period} 暂无回测记录。",
            "metric_breakdown": [],
            "overall_risk_level": "信息不足",
            "warning_signals": [],
        }

    metric_groups = _group_by_metric(target_rows)
    metric_breakdown = []
    warning_signals = []
    weak_metrics = []
    stable_metrics = []

    for metric_name, metric_rows in metric_groups.items():
        metric_rows = _sort_rows_for_trend(metric_rows)
        match_levels = [r.get("prediction_match_level", "信息不足") for r in metric_rows]
        match_scores = [MATCH_LEVEL_ORDER.get(x, 0) for x in match_levels]
        deviations = [
            _abs_or_none(_safe_float(r.get("deviation_pct_display")))
            for r in metric_rows
            if _safe_float(r.get("deviation_pct_display")) is not None
        ]
        latest = metric_rows[-1]
        latest_dev = _safe_float(latest.get("deviation_pct_display"))
        latest_match = latest.get("prediction_match_level", "信息不足")

        trend_signal = "稳定"
        if len(metric_rows) >= 2:
            last_two = metric_rows[-2:]
            d1 = _safe_float(last_two[0].get("deviation_pct_display"))
            d2 = _safe_float(last_two[1].get("deviation_pct_display"))
            if d1 is not None and d2 is not None:
                if abs(d2) > abs(d1) + 3:
                    trend_signal = "恶化"
                elif abs(d2) + 3 < abs(d1):
                    trend_signal = "改善"

        avg_dev = _avg([d for d in deviations if d is not None])
        med_dev = _median([d for d in deviations if d is not None])
        avg_score = _avg(match_scores)

        metric_breakdown.append({
            "metric_name": metric_name,
            "record_count": len(metric_rows),
            "latest_observation_period": latest.get("actual_observation_period", ""),
            "latest_match_level": latest_match,
            "latest_deviation_pct": latest_dev,
            "avg_match_score": round(avg_score, 3) if avg_score is not None else None,
            "avg_abs_deviation_pct": round(avg_dev, 3) if avg_dev is not None else None,
            "median_abs_deviation_pct": round(med_dev, 3) if med_dev is not None else None,
            "trend_signal": trend_signal,
        })

        if latest_match == "明显偏离" or (latest_dev is not None and abs(latest_dev) >= 20):
            weak_metrics.append(metric_name)
            warning_signals.append(f"{metric_name} 最新偏差较大，需优先复盘。")
        elif latest_match == "符合" and (latest_dev is not None and abs(latest_dev) <= 8):
            stable_metrics.append(metric_name)

        if trend_signal == "恶化":
            warning_signals.append(f"{metric_name} 偏差呈恶化趋势。")

    overall_risk_level = "低"
    if len(weak_metrics) >= 2:
        overall_risk_level = "高"
    elif len(weak_metrics) == 1:
        overall_risk_level = "中"

    summary_parts = [
        f"{target_period} 共 {len(target_rows)} 条回测记录，覆盖 {len(metric_groups)} 个指标。"
    ]

    if weak_metrics:
        summary_parts.append("当前最需要关注的失真指标：" + "、".join(sorted(set(weak_metrics))) + "。")
    if stable_metrics:
        summary_parts.append("相对稳定的指标：" + "、".join(sorted(set(stable_metrics))) + "。")

    if not weak_metrics and not stable_metrics:
        summary_parts.append("当前缺少足够清晰的稳定/失真分层，需继续观察。")

    summary_parts.append(f"整体回测风险等级：{overall_risk_level}。")

    return {
        "forecast_target_period": target_period,
        "summary_text": "".join(summary_parts),
        "metric_breakdown": sorted(metric_breakdown, key=lambda x: (x.get("metric_name", ""))),
        "overall_risk_level": overall_risk_level,
        "warning_signals": sorted(list(set(warning_signals))),
    }


def build_all_target_retro_summaries(company_folder: str | Path) -> List[dict]:
    rows = build_backtest_overview_rows(company_folder)
    targets = sorted(list({r.get("forecast_target_period", "") for r in rows if r.get("forecast_target_period", "")}))
    return [build_target_period_retro_summary(rows, target) for target in targets]


def build_metric_warning_signals(rows: List[dict]) -> List[dict]:
    metric_groups = _group_by_metric(rows)
    results = []

    for metric_name, metric_rows in metric_groups.items():
        metric_rows = _sort_rows_for_trend(metric_rows)
        latest = metric_rows[-1]
        latest_dev = _safe_float(latest.get("deviation_pct_display"))
        latest_match = latest.get("prediction_match_level", "信息不足")

        worsening_count = 0
        if len(metric_rows) >= 3:
            recent = metric_rows[-3:]
            devs = [_safe_float(x.get("deviation_pct_display")) for x in recent]
            if all(v is not None for v in devs):
                if abs(devs[2]) > abs(devs[1]) > abs(devs[0]):
                    worsening_count = 1

        signal_level = "低"
        signal_reason = []

        if latest_match == "明显偏离":
            signal_level = "高"
            signal_reason.append("最新一轮回测已明显偏离。")

        if latest_dev is not None and abs(latest_dev) >= 20:
            signal_level = "高"
            signal_reason.append("最新绝对偏差超过 20%。")
        elif latest_dev is not None and abs(latest_dev) >= 10 and signal_level != "高":
            signal_level = "中"
            signal_reason.append("最新绝对偏差超过 10%。")

        if worsening_count:
            signal_level = "高" if signal_level != "高" else signal_level
            signal_reason.append("最近三次偏差连续恶化。")

        if latest_match == "符合" and latest_dev is not None and abs(latest_dev) <= 8 and not worsening_count:
            signal_level = "低"
            if not signal_reason:
                signal_reason.append("最新偏差较小且未见明显恶化。")

        results.append({
            "metric_name": metric_name,
            "latest_observation_period": latest.get("actual_observation_period", ""),
            "latest_match_level": latest_match,
            "latest_deviation_pct": latest_dev,
            "warning_level": signal_level,
            "warning_reason": "；".join(signal_reason) if signal_reason else "暂无明确信号。",
        })

    level_order = {"高": 3, "中": 2, "低": 1}
    results.sort(key=lambda x: (-level_order.get(x.get("warning_level", "低"), 1), x.get("metric_name", "")))
    return results


def build_deviation_heatmap_table(rows: List[dict]) -> List[dict]:
    """
    输出适合 dataframe 展示的“热力图底表”
    行：actual_observation_period
    列：metric_name
    值：deviation_pct_display
    """
    metric_names = sorted(list({r.get("metric_name", "") for r in rows if r.get("metric_name", "")}))
    periods = sorted(
        list({r.get("actual_observation_period", "") for r in rows if r.get("actual_observation_period", "")}),
        key=period_sort_tuple
    )

    results = []
    for period in periods:
        row = {
            "actual_observation_period": period,
        }
        period_rows = [r for r in rows if r.get("actual_observation_period", "") == period]
        for metric_name in metric_names:
            candidate = None
            matching = [r for r in period_rows if r.get("metric_name", "") == metric_name]
            if matching:
                matching = _sort_rows_for_trend(matching)
                candidate = matching[-1]
            row[metric_name] = candidate.get("deviation_pct_display") if candidate else None
        results.append(row)

    return results


def build_backtest_review_report(company_folder: str | Path) -> dict:
    rows = build_backtest_overview_rows(company_folder)
    target_summaries = build_all_target_retro_summaries(company_folder)
    warnings = build_metric_warning_signals(rows)
    heatmap_rows = build_deviation_heatmap_table(rows)

    overall_warning = "低"
    if any(item.get("warning_level") == "高" for item in warnings):
        overall_warning = "高"
    elif any(item.get("warning_level") == "中" for item in warnings):
        overall_warning = "中"

    top_risks = [w["metric_name"] for w in warnings if w.get("warning_level") == "高"][:3]

    executive_summary_parts = []
    executive_summary_parts.append(f"当前共纳入 {len(rows)} 条回测记录。")
    if target_summaries:
        executive_summary_parts.append(f"覆盖 {len(target_summaries)} 个目标期。")
    if top_risks:
        executive_summary_parts.append("高优先级失真指标包括：" + "、".join(top_risks) + "。")
    executive_summary_parts.append(f"整体预警等级：{overall_warning}。")

    return {
        "company_name": Path(company_folder).name,
        "generated_at": "",
        "overall_warning_level": overall_warning,
        "executive_summary": "".join(executive_summary_parts),
        "target_period_summaries": target_summaries,
        "metric_warning_signals": warnings,
        "deviation_heatmap_rows": heatmap_rows,
    }