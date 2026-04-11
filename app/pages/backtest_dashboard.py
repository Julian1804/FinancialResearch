import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from services.backtest_dashboard_service import (
    build_backtest_health_summary,
    build_backtest_matrix,
    build_backtest_overview_rows,
    build_metric_trend_chart_rows,
    build_metric_trend_rows,
    build_target_period_summary,
)
from services.company_ui_service import format_company_option, get_company_folder_path, get_company_select_values
from services.repository_service import refresh_company_repository


def backtest_dashboard_page():
    st.title("多指标联合回测总览 + 偏差趋势可视化")

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
        if st.button("重新读取回测结果"):
            st.rerun()

    rows = build_backtest_overview_rows(company_folder)
    if not rows:
        st.info("当前还没有 forecast_check 结果。请先去 forecast_check 页面生成回测。")
        return

    health = build_backtest_health_summary(rows)

    st.markdown("## 回测健康度总览")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("回测记录数", health.get("record_count", 0))
    with c2:
        st.metric("覆盖指标数", health.get("metric_count", 0))
    with c3:
        avg_dev = health.get("avg_abs_deviation_pct")
        st.metric("平均绝对偏差(%)", avg_dev if avg_dev is not None else "N/A")

    st.markdown("### 匹配等级分布")
    dist = health.get("match_distribution", {})
    dist_rows = [{"prediction_match_level": k, "count": v} for k, v in dist.items()]
    if dist_rows:
        st.dataframe(pd.DataFrame(dist_rows), use_container_width=True)

    st.markdown("## 目标期回测汇总")
    target_summary = build_target_period_summary(rows)
    if target_summary:
        st.dataframe(pd.DataFrame(target_summary), use_container_width=True)

    st.markdown("## 全量回测明细")
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True)

    st.markdown("## 多指标联合矩阵")
    matrix_rows = build_backtest_matrix(rows)
    if matrix_rows:
        st.dataframe(pd.DataFrame(matrix_rows), use_container_width=True)

    st.markdown("## 指标偏差趋势")
    metric_names = sorted(list({row.get("metric_name", "") for row in rows if row.get("metric_name", "")}))
    if metric_names:
        selected_metric = st.selectbox("请选择指标查看趋势", options=metric_names, index=0)
        trend_rows = build_metric_trend_rows(rows, selected_metric)
        trend_chart_rows = build_metric_trend_chart_rows(rows, selected_metric)

        if trend_rows:
            st.dataframe(pd.DataFrame(trend_rows), use_container_width=True)

        if trend_chart_rows:
            chart_df = pd.DataFrame(trend_chart_rows)
            chart_df = chart_df.set_index("x_label")

            st.markdown("### 偏差百分比趋势")
            if "deviation_pct" in chart_df.columns:
                st.line_chart(chart_df[["deviation_pct"]])

            st.markdown("### 匹配分数趋势")
            if "match_score" in chart_df.columns:
                st.line_chart(chart_df[["match_score"]])

            st.markdown("### 实际值 vs 预期值")
            cols = [c for c in ["actual_value", "expected_value"] if c in chart_df.columns]
            if cols:
                st.line_chart(chart_df[cols])


if __name__ == "__main__":
    backtest_dashboard_page()