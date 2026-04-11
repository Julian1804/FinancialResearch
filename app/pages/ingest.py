import sys
from pathlib import Path

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from services.company_ui_service import format_company_option, get_company_folder_path, get_company_select_values
from services.ingest_service import run_ingest_pipeline
from utils.file_utils import get_pdf_files_in_company_folder


def ingest_page():
    st.title("一体化入库（Parse → Extract → Metrics）")
    st.caption("建议日常主流程走这个页面；Parse / Extract / Metrics 三页保留，用于单步排查和调试。")

    company_values = get_company_select_values()
    if len(company_values) <= 1:
        st.warning("还没有任何公司文件夹，请先上传财报。")
        return

    selected_company = st.selectbox("请选择公司", options=company_values, index=0, format_func=format_company_option)
    if not selected_company:
        st.info("请先选择公司。")
        return

    company_folder = get_company_folder_path(selected_company)
    pdf_files = get_pdf_files_in_company_folder(company_folder)
    if not pdf_files:
        st.warning("该公司“年报”文件夹下没有 PDF 文件。")
        return

    selected_pdf = st.selectbox("请选择文件", options=[""] + [Path(x).name for x in pdf_files], index=0)
    if not selected_pdf:
        st.stop()
    selected_pdf_path = next(path for path in pdf_files if Path(path).name == selected_pdf)

    if st.button("开始一体化入库"):
        with st.spinner("正在执行主流程..."):
            result = run_ingest_pipeline(selected_company, selected_pdf_path, run_extract=True, run_metrics=True)
        st.success("一体化入库完成")
        st.json({
            "parsed_path": result.get("parsed_path", ""),
            "extracted_path": result.get("extracted_path", ""),
            "metric_names": (result.get("metrics_result") or {}).get("metric_names", []),
            "multimodal_runtime": (result.get("parsed_data") or {}).get("multimodal_runtime", {}),
        })


if __name__ == "__main__":
    ingest_page()
