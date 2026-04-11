import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from services.company_ui_service import format_company_option, get_company_folder_path, get_company_select_values
from services.metric_extraction_service import load_standardized_metrics
from utils.file_utils import load_json_file


def metrics_table_page():
    st.title("表格级财务抽取结果查看")

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
    metrics_data = load_standardized_metrics(company_folder)
    metrics = metrics_data.get("metrics", {})

    if not metrics:
        st.info("当前还没有标准化指标，请先去 metrics 页面执行自动指标抽取。")
        return

    metric_names = sorted(metrics.keys())
    selected_metric = st.selectbox("请选择指标", options=metric_names, index=0)

    candidates = metrics.get(selected_metric, [])
    if not candidates:
        st.info("当前指标没有候选。")
        return

    rows = []
    for item in candidates:
        rows.append({
            "metric_name": item.get("metric_name", ""),
            "period_key": item.get("period_key", ""),
            "value": item.get("value"),
            "value_base": item.get("value_base"),
            "prior_value": item.get("prior_value"),
            "prior_value_base": item.get("prior_value_base"),
            "unit": item.get("unit", ""),
            "yoy_percent": item.get("yoy_percent"),
            "qoq_percent": item.get("qoq_percent"),
            "source_file": item.get("source_file", ""),
            "material_timestamp": item.get("material_timestamp", ""),
            "extraction_method": item.get("extraction_method", ""),
            "score": item.get("score"),
            "snippet": item.get("snippet", ""),
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True)

    with st.expander("查看 standardized_metrics.json"):
        path = company_folder / "年报分析" / "standardized_metrics.json"
        if path.exists():
            st.json(load_json_file(path))
        else:
            st.info("文件不存在。")


if __name__ == "__main__":
    metrics_table_page()