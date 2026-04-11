import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from services.company_ui_service import format_company_option, get_company_folder_path, get_company_select_values
from services.repository_service import refresh_company_repository
from services.revision_memory_service import load_revision_log, rebuild_history_memory_with_backtest
from utils.file_utils import build_history_memory_path, load_json_file


def revision_memory_page():
    st.title("回测复盘写入 history_memory + 修正日志生成")

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

    col1, col2 = st.columns(2)
    with col1:
        if st.button("重建 history_memory 与 revision log"):
            with st.spinner("正在将回测复盘写入 history_memory，并生成修正日志..."):
                result = rebuild_history_memory_with_backtest(company_folder)
                refresh_company_repository(company_folder)
            st.success(
                f"完成：entry_count={result.get('entry_count', 0)}，revision_count={result.get('revision_count', 0)}"
            )

    with col2:
        if st.button("重新读取结果"):
            st.rerun()

    history_path = Path(build_history_memory_path(company_folder))
    if history_path.exists():
        history_memory = load_json_file(history_path)
        backtest_memory = history_memory.get("backtest_memory", {})

        st.markdown("## history_memory 中的回测记忆概览")
        c1, c2 = st.columns(2)
        with c1:
            st.metric("backtest entries", backtest_memory.get("entry_count", 0))
        with c2:
            st.metric("revision logs", backtest_memory.get("revision_count", 0))

        latest_entry = backtest_memory.get("latest_entry", {})
        if latest_entry:
            st.markdown("### latest_entry")
            st.json(latest_entry)

        target_period_summaries = backtest_memory.get("target_period_summaries", [])
        if target_period_summaries:
            st.markdown("### target_period_summaries")
            st.dataframe(pd.DataFrame(target_period_summaries), use_container_width=True)

        with st.expander("查看 history_memory.json 原始内容"):
            st.json(history_memory)
    else:
        st.info("当前还没有 history_memory.json。")

    revision_log = load_revision_log(company_folder)
    revisions = revision_log.get("revisions", [])
    st.markdown("## 修正日志（revision log）")
    if revisions:
        st.dataframe(pd.DataFrame(revisions), use_container_width=True)
    else:
        st.info("当前还没有 revision log。")

    with st.expander("查看 backtest_revision_log.json 原始内容"):
        st.json(revision_log)


if __name__ == "__main__":
    revision_memory_page()