import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from services.backtest_report_service import (
    build_all_target_retro_summaries,
    build_backtest_review_report,
    build_deviation_heatmap_table,
    build_metric_warning_signals,
)
from services.backtest_dashboard_service import build_backtest_overview_rows
from services.company_ui_service import format_company_option, get_company_folder_path, get_company_select_values
from services.repository_service import refresh_company_repository


def backtest_report_page():
    st.title("自动生成回测复盘摘要 + 偏差热力图 + 预警信号总结")

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
        if st.button("重新生成复盘视图"):
            st.rerun()

    rows = build_backtest_overview_rows(company_folder)
    if not rows:
        st.info("当前还没有 forecast_check 结果，请先去 forecast_check 页面生成。")
        return

    review_report = build_backtest_review_report(company_folder)
    st.markdown("## 执行摘要")
    st.write(review_report.get("executive_summary", ""))

    st.markdown("## 目标期复盘摘要")
    target_summaries = build_all_target_retro_summaries(company_folder)
    if target_summaries:
        for item in target_summaries:
            with st.expander(f"{item.get('forecast_target_period', '')} ｜ 风险等级：{item.get('overall_risk_level', '')}", expanded=False):
                st.write(item.get("summary_text", ""))
                warning_signals = item.get("warning_signals", [])
                if warning_signals:
                    st.markdown("### 预警点")
                    for w in warning_signals:
                        st.write(f"- {w}")

                metric_breakdown = item.get("metric_breakdown", [])
                if metric_breakdown:
                    st.markdown("### 指标拆解")
                    st.dataframe(pd.DataFrame(metric_breakdown), use_container_width=True)

    st.markdown("## 指标预警信号总结")
    warning_rows = build_metric_warning_signals(rows)
    if warning_rows:
        st.dataframe(pd.DataFrame(warning_rows), use_container_width=True)

    st.markdown("## 偏差热力图底表")
    heatmap_rows = build_deviation_heatmap_table(rows)
    if heatmap_rows:
        heatmap_df = pd.DataFrame(heatmap_rows)
        st.dataframe(heatmap_df, use_container_width=True)

        st.markdown("### 偏差热力图（颜色映射）")
        metric_columns = [c for c in heatmap_df.columns if c != "actual_observation_period"]
        if metric_columns:
            styled = heatmap_df.style.background_gradient(cmap="RdYlGn_r", subset=metric_columns)
            st.dataframe(styled, use_container_width=True)
    else:
        st.info("暂无热力图数据。")

    st.markdown("## 原始回测记录")
    st.dataframe(pd.DataFrame(rows), use_container_width=True)


if __name__ == "__main__":
    backtest_report_page()