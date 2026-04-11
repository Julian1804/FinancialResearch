from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from services.backtest_report_service import build_all_target_retro_summaries
from services.research_utils import now_iso
from services.revision_memory_service import load_revision_log


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _get_revision_change_summary(prev_entry: dict, curr_entry: dict) -> str:
    prev_match = prev_entry.get("from_match_level") or prev_entry.get("prediction_match_level", "信息不足")
    curr_match = curr_entry.get("to_match_level") or curr_entry.get("prediction_match_level", "信息不足")

    prev_deviation = _safe_float(prev_entry.get("from_deviation_pct", prev_entry.get("deviation_pct", 0.0)))
    curr_deviation = _safe_float(curr_entry.get("to_deviation_pct", curr_entry.get("deviation_pct", 0.0)))

    metric_name = curr_entry.get("metric_name", "该指标")
    target_period = curr_entry.get("forecast_target_period", "目标期")
    from_period = prev_entry.get("from_actual_observation_period") or prev_entry.get("actual_observation_period", "")
    to_period = curr_entry.get("to_actual_observation_period") or curr_entry.get("actual_observation_period", "")

    summary: List[str] = [f"{metric_name} 对 {target_period} 的跟踪，从 {from_period} 到 {to_period}："]

    if prev_match != curr_match:
        summary.append(f"判断等级由“{prev_match}”变为“{curr_match}”。")

    if prev_deviation is not None and curr_deviation is not None:
        if abs(curr_deviation) > abs(prev_deviation):
            summary.append(f"偏差扩大 {round(abs(curr_deviation - prev_deviation), 2)} 个百分点。")
        elif abs(curr_deviation) < abs(prev_deviation):
            summary.append(f"偏差收敛 {round(abs(prev_deviation - curr_deviation), 2)} 个百分点。")
        else:
            summary.append("偏差基本持平。")

    recommendation = curr_entry.get("to_updated_recommendation") or curr_entry.get("updated_recommendation", "")
    if recommendation:
        summary.append(f"当前建议：{recommendation}。")

    return "".join(summary)


def _normalize_current_metrics(current_report: Dict[str, Any]) -> List[dict]:
    metrics = current_report.get("kpi_data", []) or []
    normalized = []
    for row in metrics:
        if isinstance(row, dict):
            normalized.append(row)
        else:
            normalized.append({"kpi_name": str(row), "current_value": "N/A"})
    return normalized


def _build_warning_signals(company_folder: str | Path, current_report: Dict[str, Any]) -> List[str]:
    page_signals = list(current_report.get("warning_signals", []) or [])
    retro_summaries = build_all_target_retro_summaries(company_folder)
    retro_signals: List[str] = []
    for item in retro_summaries:
        retro_signals.extend(item.get("warning_signals", []) or [])
    merged = []
    for signal in page_signals + retro_signals:
        signal = str(signal).strip()
        if signal and signal not in merged:
            merged.append(signal)
    return merged


def build_decision_support_report(company_folder: str | Path, current_report: Dict[str, Any]) -> Dict[str, Any]:
    company_folder = Path(company_folder)
    revision_log = load_revision_log(company_folder)
    revisions = revision_log.get("revisions", []) or []

    summary_lines: List[str] = []
    for prev, curr in zip(revisions[:-1], revisions[1:]):
        summary_lines.append(_get_revision_change_summary(prev, curr))

    retro_summaries = build_all_target_retro_summaries(company_folder)
    high_risk_targets = [
        item.get("forecast_target_period", "")
        for item in retro_summaries
        if item.get("overall_risk_level") == "高"
    ]

    executive_summary = []
    if high_risk_targets:
        executive_summary.append("高风险目标期：" + "、".join(high_risk_targets) + "。")
    if not high_risk_targets and retro_summaries:
        executive_summary.append("当前未识别到高风险目标期，但仍需持续观察关键指标偏差。")
    if summary_lines:
        executive_summary.append("最近修正摘要：" + summary_lines[-1])

    return {
        "generated_at": now_iso(),
        "company_name": company_folder.name,
        "summary_text": "\n".join(summary_lines),
        "executive_summary": "".join(executive_summary),
        "current_metrics": _normalize_current_metrics(current_report),
        "warning_signals": _build_warning_signals(company_folder, current_report),
        "forecast_target_period": current_report.get("forecast_target_period", ""),
        "forecast": current_report.get("forecast", {}),
        "retro_summaries": retro_summaries,
    }
