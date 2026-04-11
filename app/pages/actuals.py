import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from services.actual_metric_service import build_actual_metric_registry, load_actual_metric_registry
from services.company_ui_service import format_company_option, get_company_folder_path, get_company_select_values


def actuals_page():
    st.title("Actuals 主时序硬数值生成")
    st.caption("只允许主财报（financial_report + 主时序）进入 actual_metrics_registry；辅助材料只能用于修正预期，不能冒充最终 actual。")

    company_values = get_company_select_values()
    if len(company_values) <= 1:
        st.warning("还没有任何公司文件夹。")
        return

    selected_company = st.selectbox("请选择公司", options=company_values, index=0, format_func=format_company_option)
    if not selected_company:
        st.info("请先选择公司。")
        return

    company_folder = get_company_folder_path(selected_company)
    if st.button("生成 actual_metrics_registry.json", type="primary"):
        result = build_actual_metric_registry(company_folder)
        st.success(f"生成完成：status={result.get('status', '')}")

    registry = load_actual_metric_registry(company_folder)
    rows = []
    for metric_name, items in registry.get("actual_metrics", {}).items():
        for item in items:
            rows.append({
                "metric_name": metric_name,
                "period_key": item.get("period_key", ""),
                "value": item.get("value"),
                "unit": item.get("unit", ""),
                "source_file": item.get("source_file", ""),
                "document_type": item.get("document_type", ""),
                "source_role": item.get("source_role", ""),
                "material_timestamp": item.get("material_timestamp", ""),
            })

    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch")
    else:
        st.info("当前还没有 actual metrics。")


if __name__ == "__main__":
    actuals_page()
