from pathlib import Path
from typing import List, Dict, Any

from services.revision_memory_service import load_revision_log
from services.master_report_service import _safe_float
from services.research_utils import now_iso
from utils.file_utils import load_json_file


def _generate_summary_text(previous_data: Dict[str, Any], current_data: Dict[str, Any]) -> str:
    """
    生成预期变化的摘要内容，包括：
    - 判断变化
    - 偏差变化
    """
    previous_match_level = previous_data.get("prediction_match_level", "信息不足")
    current_match_level = current_data.get("prediction_match_level", "信息不足")
    previous_deviation = previous_data.get("deviation_pct", 0.0)
    current_deviation = current_data.get("deviation_pct", 0.0)

    summary = []
    if previous_match_level != current_match_level:
        summary.append(f"回测判断等级从“{previous_match_level}”变为“{current_match_level}”。")

    if abs(current_deviation) > abs(previous_deviation):
        summary.append(f"偏差增大了：{round(abs(current_deviation - previous_deviation), 2)} 个百分点。")
    elif abs(current_deviation) < abs(previous_deviation):
        summary.append(f"偏差收敛了：{round(abs(previous_deviation - current_deviation), 2)} 个百分点。")
    else:
        summary.append("偏差变化不大。")

    return "；".join(summary)


def _combine_kpi_and_warnings(kpi_data: List[dict], warning_signals: List[str]) -> str:
    """
    将 KPI 数据和警告信号结合，生成详细的复盘报告部分
    """
    kpi_summary = []
    for kpi in kpi_data:
        kpi_summary.append(f"- {kpi.get('kpi_name', '未定义 KPI')}：{kpi.get('current_value', 'N/A')}")

    warning_summary = []
    for signal in warning_signals:
        warning_summary.append(f"- {signal}")

    return "\n".join(kpi_summary + warning_summary)


def build_summary_report(company_folder: str | Path, current_report: Dict[str, Any]) -> Dict[str, Any]:
    """
    生成本期相对上期预期变化摘要，并生成包含 KPI 和预警信号的复盘报告
    """
    revision_log = load_revision_log(company_folder)
    revisions = revision_log.get("revisions", [])

    summary_text = []
    for prev, curr in zip(revisions[:-1], revisions[1:]):
        summary_text.append(_generate_summary_text(prev, curr))

    kpi_data = current_report.get("kpi_data", [])
    warning_signals = current_report.get("warning_signals", [])

    kpi_and_warning_report = _combine_kpi_and_warnings(kpi_data, warning_signals)

    return {
        "generated_at": now_iso(),
        "company_name": company_folder.name,
        "summary_text": "\n".join(summary_text),
        "kpi_and_warning_report": kpi_and_warning_report,
    }