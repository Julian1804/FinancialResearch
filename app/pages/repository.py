import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from services.company_ui_service import format_company_option, get_company_folder_path, get_company_select_values
from services.forecast_service import build_forecast_overview_rows
from services.repository_service import refresh_company_repository, load_company_repository_snapshot
from services.sqlite_index_service import fetch_company_documents
from utils.file_utils import (
    build_forecast_registry_path,
    build_history_memory_path,
    build_index_json_path,
    build_metric_registry_path,
    build_timeline_json_path,
    load_json_file,
)


def repository_page():
    st.title("公司资料总览 / 索引管理")

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
                f"索引已刷新：documents={snapshot.get('summary', {}).get('documents', 0)}，"
                f"chunks={snapshot.get('summary', {}).get('retrieval_chunks', 0)}"
            )

    with col2:
        if st.button("重新读取当前索引"):
            st.rerun()

    snapshot = load_company_repository_snapshot(company_folder)
    summary = snapshot.get("summary", {})

    history_memory_exists = Path(build_history_memory_path(company_folder)).exists()
    revision_log_exists = (company_folder / "年报分析" / "backtest_revision_log.json").exists()

    st.markdown("## 总览")
    st.write(f"- 公司：`{snapshot.get('company_name', '')}`")
    st.write(f"- 原始 PDF：`{summary.get('raw_pdfs', 0)}`")
    st.write(f"- parsed JSON：`{summary.get('parsed_json', 0)}`")
    st.write(f"- extracted JSON：`{summary.get('extracted_json', 0)}`")
    st.write(f"- report JSON：`{summary.get('report_json', 0)}`")
    st.write(f"- forecast_check JSON：`{summary.get('forecast_check_json', 0)}`")
    st.write(f"- forecast_snapshot JSON：`{summary.get('forecast_snapshot_json', 0)}`")
    st.write(f"- metric_registry：`{'已存在' if summary.get('metric_registry_exists') else '未生成'}`")
    st.write(f"- forecast_registry：`{'已存在' if summary.get('forecast_registry_exists') else '未生成'}`")
    st.write(f"- standardized_metrics：`{'已存在' if summary.get('standardized_metrics_exists') else '未生成'}`")
    st.write(f"- metric_extraction_registry：`{'已存在' if summary.get('metric_extraction_registry_exists') else '未生成'}`")
    st.write(f"- actual_metrics_registry：`{'已存在' if summary.get('actual_metrics_registry_exists') else '未生成'}`")
    st.write(f"- history_memory：`{'已存在' if history_memory_exists else '未生成'}`")
    st.write(f"- backtest_revision_log：`{'已存在' if revision_log_exists else '未生成'}`")
    st.write(f"- SQLite chunks：`{summary.get('retrieval_chunks', 0)}`")

    st.markdown("## 时间轴总览")
    timeline = snapshot.get("timeline", [])
    if timeline:
        st.dataframe(timeline, use_container_width=True)
    else:
        st.info("当前没有可展示的时间轴记录。")

    st.markdown("## 文档索引（SQLite）")
    docs = fetch_company_documents(selected_company)
    if docs:
        display_rows = []
        for doc in docs:
            display_rows.append({
                "source_doc_id": doc.get("source_doc_id", ""),
                "source_file": doc.get("source_file", ""),
                "source_type": doc.get("source_type", ""),
                "period_key": doc.get("period_key", ""),
                "report_type": doc.get("report_type", ""),
                "document_type": doc.get("document_type", ""),
                "主财报": "是" if doc.get("is_primary_financial_report") else "否",
                "可修正预测": "是" if doc.get("can_adjust_forecast") else "否",
                "json_path": doc.get("json_path", ""),
            })
        st.dataframe(display_rows, use_container_width=True)
    else:
        st.info("SQLite 中还没有该公司的文档记录。")

    st.markdown("## 预测快照总览")
    forecast_rows = build_forecast_overview_rows(company_folder)
    if forecast_rows:
        st.dataframe(pd.DataFrame(forecast_rows), use_container_width=True)
    else:
        st.info("当前还没有 forecast snapshot。")

    with st.expander("查看 index.json 原始内容"):
        index_path = build_index_json_path(company_folder)
        if Path(index_path).exists():
            st.json(load_json_file(index_path))
        else:
            st.info("index.json 尚未生成。")

    with st.expander("查看 timeline_index.json 原始内容"):
        timeline_path = build_timeline_json_path(company_folder)
        if Path(timeline_path).exists():
            st.json(load_json_file(timeline_path))
        else:
            st.info("timeline_index.json 尚未生成。")

    with st.expander("查看 metric_series_registry.json 原始内容"):
        metric_path = build_metric_registry_path(company_folder)
        if Path(metric_path).exists():
            st.json(load_json_file(metric_path))
        else:
            st.info("metric_series_registry.json 尚未生成。")

    with st.expander("查看 forecast_registry.json 原始内容"):
        forecast_path = build_forecast_registry_path(company_folder)
        if Path(forecast_path).exists():
            st.json(load_json_file(forecast_path))
        else:
            st.info("forecast_registry.json 尚未生成。")

    with st.expander("查看 history_memory.json 原始内容"):
        path = Path(build_history_memory_path(company_folder))
        if path.exists():
            st.json(load_json_file(path))
        else:
            st.info("history_memory.json 尚未生成。")

    with st.expander("查看 backtest_revision_log.json 原始内容"):
        path = company_folder / "年报分析" / "backtest_revision_log.json"
        if path.exists():
            st.json(load_json_file(path))
        else:
            st.info("backtest_revision_log.json 尚未生成。")


if __name__ == "__main__":
    repository_page()