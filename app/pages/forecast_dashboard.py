import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from services.company_ui_service import format_company_option, get_company_folder_path, get_company_select_values
from services.forecast_service import (
    build_forecast_overview_rows,
    build_snapshot_matrix,
    load_forecast_registry,
)
from services.repository_service import refresh_company_repository
from utils.file_utils import build_forecast_registry_path, load_json_file


def forecast_dashboard_page():
    st.title("多指标联动预测总览页")

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
                f"索引已刷新：forecast_snapshot={snapshot.get('summary', {}).get('forecast_snapshot_json', 0)}"
            )
    with col2:
        if st.button("重新读取预测注册表"):
            st.rerun()

    registry = load_forecast_registry(company_folder)
    snapshots = registry.get("snapshots", [])

    if not snapshots:
        st.info("当前还没有 forecast snapshot。请先到 forecast 页面生成至少一份 snapshot。")
        return

    st.markdown("## 预测快照流水")
    rows = build_forecast_overview_rows(company_folder)
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True)
    else:
        st.info("当前没有可展示的预测快照。")

    anchor_options = sorted(list({item.get("forecast_as_of_period", "") for item in rows if item.get("forecast_as_of_period")}))
    target_options = sorted(list({item.get("forecast_target_period", "") for item in rows if item.get("forecast_target_period")}))

    col_a, col_b = st.columns(2)
    with col_a:
        selected_anchor = st.selectbox("筛选预测时点", options=["全部"] + anchor_options, index=0)
    with col_b:
        selected_target = st.selectbox("筛选目标期", options=["全部"] + target_options, index=0)

    filtered_rows = rows
    if selected_anchor != "全部":
        filtered_rows = [r for r in filtered_rows if r.get("forecast_as_of_period") == selected_anchor]
    if selected_target != "全部":
        filtered_rows = [r for r in filtered_rows if r.get("forecast_target_period") == selected_target]

    st.markdown("## 多指标联动矩阵")
    matrix_rows = build_snapshot_matrix(filtered_rows)
    if matrix_rows:
        st.dataframe(pd.DataFrame(matrix_rows), use_container_width=True)
    else:
        st.info("当前筛选条件下没有矩阵数据。")

    registry_path = build_forecast_registry_path(company_folder)
    if Path(registry_path).exists():
        with st.expander("查看 forecast_registry.json 原始内容"):
            st.json(load_json_file(registry_path))


if __name__ == "__main__":
    forecast_dashboard_page()