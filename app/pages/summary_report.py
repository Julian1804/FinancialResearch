import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from services.company_ui_service import format_company_option, get_company_folder_path, get_company_select_values
from services.summary_report_service import build_summary_report
from services.repository_service import refresh_company_repository
from utils.file_utils import save_json_file


def summary_report_page():
    st.title("生成“本期相对上期预期变化摘要”的复盘报告，并关联 KPI 和预警信号")

    company_values = get_company_select_values()
    if len(company_values) <= 1:
        st.warning("还没有任何公司文件夹。")
        return

    selected_company = st.selectbox(
        "请选择公司",
        options=company_values,
        index=0,
        format_func=format_company_option,
    )
    if not selected_company:
        st.info("请先选择公司。")
        return

    company_folder = get_company_folder_path(selected_company)

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("刷新公司索引"):
            snapshot = refresh_company_repository(company_folder)
            st.success(
                f"索引已刷新：forecast_check={snapshot.get('summary', {}).get('forecast_check_json', 0)}"
            )
    with col2:
        if st.button("重新读取当前报告"):
            st.rerun()

    st.markdown("## 自动生成复盘报告")
    current_report_data = {
        "company_name": selected_company,
        "generated_at": "",
        "forecast_target_period": "2025FY",
        "metrics": ["revenue", "net_profit", "gross_margin"],
        "summary": "本报告总结了公司的整体财务表现与预期。",
        "kpi_data": [
            {"kpi_name": "revenue", "current_value": "10亿"},
            {"kpi_name": "net_profit", "current_value": "2亿"},
        ],
        "warning_signals": [
            "净利润偏差较大，需优先复盘。",
            "毛利率出现下滑趋势。",
        ],
    }

    summary_report = build_summary_report(company_folder, current_report_data)

    st.markdown("### 本期相对上期预期变化摘要")
    st.write(summary_report["summary_text"])

    st.markdown("### KPI 和预警信号关联报告")
    st.write(summary_report["kpi_and_warning_report"])

    with st.expander("查看原始报告数据"):
        st.json(summary_report)

    save_path = Path(company_folder) / "年报分析" / "summary_report_with_kpi_and_warnings.json"
    if st.button("保存当前报告"):
        save_json_file(summary_report, save_path)
        st.success(f"报告已保存到：{save_path}")


if __name__ == "__main__":
    summary_report_page()