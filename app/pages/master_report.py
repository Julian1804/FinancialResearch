import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from services.company_ui_service import format_company_option, get_company_folder_path, get_company_select_values
from services.master_report_service import generate_master_report_with_revision_summary
from services.repository_service import refresh_company_repository
from utils.file_utils import load_json_file, save_json_file


def master_report_page():
    st.title("生成 Master Report + 本期相对上期预期变化摘要")

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

    st.markdown("## Master Report 自动生成")
    current_report_data = {
        "company_name": selected_company,
        "generated_at": "",
        "forecast_target_period": "2025FY",
        "metrics": ["revenue", "net_profit", "gross_margin"],
        "summary": "本报告总结了公司的整体财务表现与预期。",
    }

    master_report = generate_master_report_with_revision_summary(company_folder, current_report_data)

    st.markdown("### 本期相对上期预期变化摘要")
    st.write("### 修正日志")
    revision_summaries = master_report.get("revision_summaries", [])
    if revision_summaries:
        st.dataframe(pd.DataFrame(revision_summaries), use_container_width=True)
    else:
        st.info("当前没有修正日志记录。")

    st.markdown("### Master Report 汇总")
    st.write(master_report["summary"])

    with st.expander("查看 Master Report 原始数据"):
        st.json(master_report)

    save_path = Path(company_folder) / "年报分析" / "master_report_with_revision.json"
    if st.button("保存当前 Master Report"):
        save_json_file(master_report, save_path)
        st.success(f"报告已保存到：{save_path}")


if __name__ == "__main__":
    master_report_page()