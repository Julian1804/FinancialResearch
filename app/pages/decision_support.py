import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from services.company_ui_service import format_company_option, get_company_folder_path, get_company_select_values
from services.decision_support_service import build_decision_support_report
from services.repository_service import refresh_company_repository
from utils.file_utils import save_json_file


def decision_support_page():
    st.title("自动生成预期修正报告并提供决策支持")

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

    st.markdown("## 决策支持报告自动生成")
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
        "forecast": {"revenue": "10亿", "net_profit": "2亿", "gross_margin": "30%"},
    }

    decision_support_report = build_decision_support_report(company_folder, current_report_data)

    st.markdown("### 预期修正报告摘要")
    st.write(decision_support_report["summary_text"])

    st.markdown("### KPI 和预警信号关联报告")
    st.write(f"KPI 数据：\n{decision_support_report['current_metrics']}")
    st.write(f"预警信号：\n{decision_support_report['warning_signals']}")

    st.markdown("### 当前预测")
    st.write(f"当前预测：\n{decision_support_report['forecast']}")

    with st.expander("查看决策支持报告原始数据"):
        st.json(decision_support_report)

    save_path = Path(company_folder) / "年报分析" / "decision_support_report.json"
    if st.button("保存当前决策支持报告"):
        save_json_file(decision_support_report, save_path)
        st.success(f"报告已保存到：{save_path}")


if __name__ == "__main__":
    decision_support_page()