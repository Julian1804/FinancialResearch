from pathlib import Path
from typing import List, Dict, Any
from services.revision_memory_service import load_revision_log
from services.period_service import period_sort_tuple
from utils.file_utils import load_json_file


def _safe_float(value: Any) -> float:
    try:
        return float(value) if value else 0.0
    except Exception:
        return 0.0


def _sort_rows_for_trend(rows: List[dict]) -> List[dict]:
    return sorted(
        rows,
        key=lambda x: (
            x.get("forecast_target_period", ""),
            period_sort_tuple(x.get("actual_observation_period", "")),
            x.get("generated_at", ""),
        )
    )


def _get_revision_change_summary(prev_entry: dict, curr_entry: dict) -> str:
    """
    对比上期与当前期，生成预期变化的描述
    """
    prev_match = prev_entry.get("prediction_match_level", "信息不足")
    curr_match = curr_entry.get("prediction_match_level", "信息不足")
    prev_deviation = prev_entry.get("deviation_pct", 0.0)
    curr_deviation = curr_entry.get("deviation_pct", 0.0)

    summary = []
    if prev_match != curr_match:
        summary.append(f"回测判断等级从“{prev_match}”变为“{curr_match}”。")

    if abs(curr_deviation) > abs(prev_deviation):
        summary.append(f"偏差增大了：{round(abs(curr_deviation - prev_deviation), 2)} 个百分点。")
    elif abs(curr_deviation) < abs(prev_deviation):
        summary.append(f"偏差收敛了：{round(abs(prev_deviation - curr_deviation), 2)} 个百分点。")
    else:
        summary.append("偏差变化不大。")

    return "；".join(summary)


def _build_revision_change_summaries(entries: List[dict]) -> List[dict]:
    """
    生成修正日志，每一条回测记录对比上一期的预期变化摘要
    """
    summaries = []
    sorted_entries = _sort_rows_for_trend(entries)

    for prev, curr in zip(sorted_entries[:-1], sorted_entries[1:]):
        summary_text = _get_revision_change_summary(prev, curr)
        summaries.append({
            "forecast_target_period": curr.get("forecast_target_period", ""),
            "metric_name": curr.get("metric_name", ""),
            "from_actual_observation_period": prev.get("actual_observation_period", ""),
            "to_actual_observation_period": curr.get("actual_observation_period", ""),
            "summary_text": summary_text,
        })

    return summaries


def load_and_summarize_revision_log(company_folder: str | Path) -> List[dict]:
    revision_log_path = Path(company_folder) / "年报分析" / "backtest_revision_log.json"
    if not revision_log_path.exists():
        return []
    
    revision_log = load_json_file(revision_log_path)
    return _build_revision_change_summaries(revision_log.get("revisions", []))


def generate_master_report_with_revision_summary(company_folder: str | Path, current_report_data: dict) -> dict:
    """
    生成最终的 master report，结合修正日志内容生成“本期相对上期预期变化摘要”
    """
    revision_summaries = load_and_summarize_revision_log(company_folder)

    report_summary = []
    for revision in revision_summaries:
        report_summary.append({
            "metric_name": revision.get("metric_name", ""),
            "forecast_target_period": revision.get("forecast_target_period", ""),
            "summary_text": revision.get("summary_text", "")
        })

    # 拼接当前的 report 数据
    current_report_data["revision_summaries"] = report_summary

    return current_report_data