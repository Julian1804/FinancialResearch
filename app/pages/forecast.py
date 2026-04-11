import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from services.company_ui_service import format_company_option, get_company_folder_path, get_company_select_values
from services.forecast_service import (
    DEFAULT_FORECAST_METRICS,
    bsts_runtime_status,
    build_metric_registry_template,
    generate_forecast_snapshot,
    load_metric_registry,
    save_metric_registry,
)
from services.repository_service import refresh_company_repository
from utils.file_utils import (
    build_forecast_registry_path,
    build_metric_registry_path,
    load_json_file,
)


def _primary_period_rows_to_df(rows: list[dict]) -> pd.DataFrame:
    display_rows = []
    for item in rows:
        display_rows.append({
            "period_key": item.get("period_key", ""),
            "report_type": item.get("report_type", ""),
            "source_file": item.get("source_file", ""),
            "material_timestamp": item.get("material_timestamp", ""),
            "document_type": item.get("document_type", ""),
        })
    return pd.DataFrame(display_rows)


def forecast_page():
    st.title("正式 BSTS 预测页（forecast snapshot + registry）")

    runtime = bsts_runtime_status()
    if runtime["ready"]:
        st.success(runtime["message"])
    else:
        st.warning(runtime["message"])

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

    col_a, col_b = st.columns([1, 1])
    with col_a:
        if st.button("刷新公司索引"):
            snapshot = refresh_company_repository(company_folder)
            st.success(
                f"索引已刷新：documents={snapshot.get('summary', {}).get('documents', 0)}，"
                f"timeline={len(snapshot.get('timeline', []))}"
            )
    with col_b:
        if st.button("初始化 / 重建指标模板"):
            registry = build_metric_registry_template(company_folder)
            save_metric_registry(company_folder, registry)
            st.success("指标模板已重建。")

    registry = load_metric_registry(company_folder)
    primary_rows = registry.get("primary_timeline", [])
    if not primary_rows:
        st.warning("当前没有可用于预测的主时间轴文件。请先完成 extract，并确认主财报识别正确。")
        return

    st.markdown("## 主时间轴")
    st.dataframe(_primary_period_rows_to_df(primary_rows), use_container_width=True)

    metric_options = registry.get("metrics", [])
    if not metric_options:
        metric_options = DEFAULT_FORECAST_METRICS

    metric_name = st.selectbox("请选择预测指标", options=metric_options, index=0)

    metric_table = registry.get("metric_values", {}).get(metric_name, [])
    if not metric_table:
        metric_table = []
        for item in primary_rows:
            metric_table.append({
                "period_key": item.get("period_key", ""),
                "report_type": item.get("report_type", ""),
                "source_file": item.get("source_file", ""),
                "material_timestamp": item.get("material_timestamp", ""),
                "value": None,
                "unit": "",
                "notes": "",
            })

    st.markdown("## 指标录入 / 校准")
    st.caption("说明：这一层是为了保证 BSTS 用的是你确认过的数字，而不是 AI 自行猜数。后续等自动结构化抽取成熟后，这里可以半自动化。")

    metric_df = pd.DataFrame(metric_table)
    if metric_df.empty:
        metric_df = pd.DataFrame(columns=["period_key", "report_type", "source_file", "material_timestamp", "value", "unit", "notes"])

    edited_df = st.data_editor(
        metric_df,
        use_container_width=True,
        num_rows="fixed",
        hide_index=True,
        column_config={
            "period_key": st.column_config.TextColumn("period_key", disabled=True),
            "report_type": st.column_config.TextColumn("report_type", disabled=True),
            "source_file": st.column_config.TextColumn("source_file", disabled=True),
            "material_timestamp": st.column_config.TextColumn("material_timestamp", disabled=True),
            "value": st.column_config.NumberColumn("value", help="请输入该 period 对应的数值"),
            "unit": st.column_config.TextColumn("unit", help="例如：百万元 / 亿元 / %"),
            "notes": st.column_config.TextColumn("notes", help="可写来源页码、口径说明"),
        },
    )

    if st.button("保存当前指标表"):
        registry["metric_values"][metric_name] = edited_df.to_dict(orient="records")
        save_metric_registry(company_folder, registry)
        st.success(f"已保存指标：{metric_name}")
        st.write(f"保存路径：{build_metric_registry_path(company_folder)}")

    st.markdown("## 预测设置")
    anchor_options = [item.get("period_key", "") for item in primary_rows if item.get("period_key")]
    if not anchor_options:
        st.warning("主时间轴没有 period_key，无法生成预测。")
        return

    default_anchor_index = len(anchor_options) - 1
    anchor_period = st.selectbox("请选择预测时点（anchor period）", options=anchor_options, index=default_anchor_index)

    confidence_level = st.selectbox("请选择区间置信水平", options=[0.8, 0.9, 0.95], index=0)
    hmc_draws = st.number_input("HMC 采样步数（越高越慢）", min_value=50, max_value=400, value=120, step=10)
    hmc_burnin = st.number_input("HMC 预热步数", min_value=20, max_value=300, value=80, step=10)

    st.caption("说明：这版采用 BSTS 作为唯一主模型。若 anchor 是 Q1/H1/Q3，会结合历史同口径 partial→FY 桥接关系。")

    if st.button("生成 forecast snapshot"):
        progress = st.progress(0.0, text="保存当前指标表")
        registry["metric_values"][metric_name] = edited_df.to_dict(orient="records")
        save_metric_registry(company_folder, registry)
        progress.progress(0.25, text="正在运行 BSTS")
        result = generate_forecast_snapshot(
            company_folder=company_folder,
            metric_name=metric_name,
            anchor_period=anchor_period,
            confidence_level=float(confidence_level),
            hmc_draws=int(hmc_draws),
            hmc_burnin=int(hmc_burnin),
        )
        progress.progress(0.85, text="刷新公司索引")
        refresh_company_repository(company_folder)
        progress.progress(1.0, text="forecast snapshot 生成完成")

        if result.get("status") == "ok":
            st.success("forecast snapshot 已生成。")
        else:
            st.warning(f"预测状态：{result.get('status', 'unknown')}")

        st.info("说明：当前预测页已显示运行进度；真正的强制取消仍需后续引入后台任务队列。")
        st.json(result)

    st.markdown("## 预测注册表")
    forecast_registry_path = build_forecast_registry_path(company_folder)
    if Path(forecast_registry_path).exists():
        with st.expander("查看 forecast_registry.json"):
            st.json(load_json_file(forecast_registry_path))
    else:
        st.info("当前还没有 forecast_registry.json。")


if __name__ == "__main__":
    forecast_page()